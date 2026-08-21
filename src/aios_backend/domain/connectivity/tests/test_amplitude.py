from __future__ import annotations

import pytest

from aios_backend.domain.connectivity import (
    LIMITED_BY_ACHIEVABILITY,
    LIMITED_BY_LINEARITY,
    LIMITED_BY_NOISE,
    LIMITED_BY_SWEEP_RANGE,
    Amplitude,
    AmplitudeMeasurement,
    DeckSchedule,
    Level,
    MIN_SWEEP_PROBES,
    ProbeSelection,
    build_probe,
    headroom_injectors,
    choose_amplitude,
    demote_plan_amplitude,
    numerical_noise_floor,
    prior_bracket,
    select_probe_injectors,
    setpoint_changes,
    sweep_amplitudes,
    SweepRun,
)
from aios_backend.core.contracts import Role

PROBE_WELLS = ("A1", "A2", "A3")
NEIGHBOURS = {"A1": 2, "A2": 5, "A3": 9, "A4": 4, "A5": 7}
TOLERANCE = 0.05
LINEARITY = 0.15


def a_amplitude(step: float, base: float = 30.0) -> Amplitude:
    return Amplitude(
        base_level_m3_per_day=base,
        step_low_m3_per_day=step,
        step_high_m3_per_day=step,
    )


def a_run(
    well: str,
    step: float,
    *,
    actual_delta: float,
    response: float,
    base_rate: float = 30.0,
    level: Level = Level.HIGH,
) -> SweepRun:
    target = base_rate + step if level is Level.HIGH else max(base_rate - step, 0.0)
    actual = base_rate + actual_delta if level is Level.HIGH else base_rate - actual_delta
    return SweepRun(
        relative_amplitude=step / base_rate,
        well=well,
        level=level,
        target_m3_per_day=target,
        baseline_rate_m3_per_day=base_rate,
        actual_m3_per_day=actual,
        baseline_cumulative_m3=1_000.0,
        perturbed_cumulative_m3=1_000.0 + response,
    )


def a_probe(
    relative: float,
    *,
    gain: float,
    noise: float = 1.0,
    shortfall_share: float = 0.0,
    base_rate: float = 30.0,
):
    step = relative * base_rate
    runs = []
    for index, well in enumerate(PROBE_WELLS):
        undershoot = shortfall_share if index < len(PROBE_WELLS) * shortfall_share else 0.0
        realized = step * (1.0 - undershoot)
        runs.append(
            a_run(
                well,
                step,
                actual_delta=realized,
                response=gain * realized,
                base_rate=base_rate,
            )
        )
    return build_probe(relative, a_amplitude(step, base_rate), tuple(runs), noise)


def test_probe_selection_spans_neighbour_density() -> None:
    """§8.3: свип идёт по 3–4 нагнетательным с РАЗНОЙ плотностью окружения."""

    selection = select_probe_injectors(tuple(NEIGHBOURS), NEIGHBOURS, 3)
    assert len(selection.wells) == 3
    assert selection.density_spread > 0


def test_wells_pinned_at_the_pressure_limit_are_kept_out_of_the_sweep() -> None:
    """Замер 16.08 на настоящем базовом прогоне Model_Z: из 27 нагнетательных

    раннего окна 7 зажаты пределом 300 бар и целевую закачку не добирают уже
    в базовом расписании — 27 недобирает 76%, 17 — 65%, 53 — 60%, 102 — 46%,
    49 — 41%, 8 — 39%, 110 — 7%. Запас есть у 20 скважин.

    Свип по зажатой скважине не измеряет ничего: повышение уставки не
    реализуется, отношение отклика к воздействию считается от почти нулевого
    знаменателя. Отбор скважин свипа обязан идти по фактическому запасу, а не
    по одной плотности окружения — иначе замер проваливается по достижимости
    ещё на минимальной амплитуде приора (что и произошло в первом заходе).
    """

    setpoints = {"27": 80.0, "17": 90.0, "110": 15.0, "25": 35.0, "12": 40.0}
    rates = {"27": 19.04, "17": 31.50, "110": 13.89, "25": 35.83, "12": 40.0}
    free = headroom_injectors(tuple(setpoints), rates, setpoints, TOLERANCE)
    assert free == ("12", "25")
    assert "17" not in free
    assert "27" not in free
    assert "110" not in free


def test_sweep_cannot_be_built_when_too_few_wells_have_headroom() -> None:
    setpoints = {"27": 80.0, "17": 90.0, "25": 35.0}
    rates = {"27": 19.04, "17": 31.50, "25": 35.83}
    free = headroom_injectors(tuple(setpoints), rates, setpoints, TOLERANCE)
    assert len(free) < MIN_SWEEP_PROBES
    with pytest.raises(ValueError, match="запасом по давлению"):
        select_probe_injectors(free, {w: 5 for w in free}, MIN_SWEEP_PROBES)


def test_probe_selection_refuses_a_degenerate_sweep_width() -> None:
    with pytest.raises(ValueError):
        select_probe_injectors(tuple(NEIGHBOURS), NEIGHBOURS, 2)
    with pytest.raises(ValueError):
        select_probe_injectors(tuple(NEIGHBOURS), NEIGHBOURS, 5)


def test_every_perturbed_run_is_checked_against_its_target() -> None:
    """Приёмка 27: фактическая приёмистость сверяется с целевой после КАЖДОГО прогона."""

    probe = a_probe(0.2, gain=4.0, shortfall_share=0.0)
    assert len(probe.outcomes) == len(PROBE_WELLS)
    for outcome in probe.outcomes:
        assert outcome.target_m3_per_day > 0.0
        assert outcome.relative_shortfall >= 0.0
    assert all(probe.achievability_ok(TOLERANCE).values())


def test_shortfall_is_measured_per_well_not_assumed() -> None:
    step = 0.2 * 30.0
    runs = (
        a_run("A1", step, actual_delta=step, response=10.0),
        a_run("A2", step, actual_delta=step * 0.5, response=5.0),
        a_run("A3", step, actual_delta=step, response=10.0),
    )
    probe = build_probe(0.2, a_amplitude(step), runs, 1.0)
    ok = probe.achievability_ok(TOLERANCE)
    assert ok["A1"] and ok["A3"]
    assert not ok["A2"]
    assert probe.shortfalls(TOLERANCE)[0].well == "A2"


def test_systematic_shortfall_drops_the_amplitude_of_the_whole_plan() -> None:
    """Приёмка 27: систематический недобор роняет амплитуду ВСЕГО плана."""

    step = 0.4 * 30.0
    runs = tuple(
        a_run(well, step, actual_delta=step * 0.4, response=4.0) for well in PROBE_WELLS
    )
    starved = build_probe(0.4, a_amplitude(step), runs, 1.0)
    assert starved.systematic_shortfall(TOLERANCE)

    healthy = a_probe(0.1, gain=4.0)
    measurement = AmplitudeMeasurement(
        probes=(healthy, starved),
        achievability_tolerance=TOLERANCE,
        linearity_tolerance=LINEARITY,
    )
    verdict = choose_amplitude(measurement)
    assert verdict.relative_amplitude == 0.1
    assert verdict.limited_by == LIMITED_BY_ACHIEVABILITY

    plan_amplitude = a_amplitude(0.4 * 30.0)
    dropped = demote_plan_amplitude(plan_amplitude, verdict)
    assert dropped.step_m3_per_day == pytest.approx(0.1 * 30.0)
    assert dropped.step_m3_per_day < plan_amplitude.step_m3_per_day


def test_shortfall_measured_on_the_real_base_run_of_model_z() -> None:
    """Замер 16.08 на настоящем базовом прогоне Model_Z, окно 01.01.2007 + 12 мес.

    Три скважины свипа, выбранные по плотности окружения (110: 2 соседа,
    25: 9, 17: 15), в самом базовом расписании ведут себя по-разному:

    - 17 — `BHP_LIMITED` все 12 месяцев, забойное ровно на пределе 300.0 бар,
      фактическая приёмистость 31.5 м³/сут при уставке 90.0, недобор 65%;
    - 110 — `BHP_LIMITED` первые 4 месяца, дальше выходит на режим:
      13.9 м³/сут при уставке 15.0, недобор 7%;
    - 25 — `RATE_TARGET`, забойное 154 бар, 35.8 м³/сут при уставке 35.0,
      целевую закачку добирает полностью.

    Недобор существует ДО всякого возмущения, и повышать уставку у скважины,
    уже стоящей на 300 бар, бессмысленно: план проектируется на одни уровни,
    а реализуются другие. Ровно поэтому §8.2 требует регрессии на фактические
    ΔWWIR, а §8.3 — сверки факта с целью после каждого прогона.
    """

    measured = (
        ("17", 90.0, 31.495544751485188),
        ("110", 15.0, 13.89351499080658),
        ("25", 35.0, 35.833333333333336),
    )
    step = 5.0
    runs = tuple(
        SweepRun(
            relative_amplitude=step / 30.0,
            well=well,
            level=Level.HIGH,
            target_m3_per_day=setpoint,
            baseline_rate_m3_per_day=actual,
            actual_m3_per_day=actual,
            baseline_cumulative_m3=104_861.36,
            perturbed_cumulative_m3=104_861.36,
        )
        for well, setpoint, actual in measured
    )
    probe = build_probe(step / 30.0, a_amplitude(step), runs, 0.05)
    ok = probe.achievability_ok(TOLERANCE)
    assert ok["17"] is False
    assert ok["110"] is False
    assert ok["25"] is True
    assert probe.systematic_shortfall(TOLERANCE)


def test_full_sweep_on_pinned_wells_refuses_to_name_an_amplitude() -> None:
    """Полный свип 16.08 по трём точкам, три настоящих прогона OPM (975 / 948 /

    1036 с). Скважины выбраны первым, ошибочным отбором — по одной плотности
    окружения, без проверки запаса по давлению, поэтому 17 и 110 зажаты
    пределом 300 бар.

    Замеренные числа по точкам +17% / +33% / +50%:

    - фактическое воздействие почти не растёт: 64.1 → 68.9 → 74.0 м³/сут,
      хотя план требовал роста втрое, — двигается только скважина 25;
    - недобор растёт: 110 — 26% → 41% → 51%, 17 — 67% → 69% → 70%;
    - отношение отклика к воздействию не постоянно вовсе:
      15.0 → 39.4 → 63.9, дрейф 0% → 163% → 326%.

    Ни одна точка не проходит: недобор систематический на всех трёх.
    Протокол §8.3 в этом случае обязан отказаться назвать амплитуду, а не
    выбрать «наименее плохую» — и отказывается.
    """

    baseline = {
        "110": 13.89351499080658,
        "17": 31.495544751485188,
        "25": 35.833333333333336,
    }
    points = (
        (
            0.17,
            5.1,
            {"110": 20.1, "17": 95.1, "25": 40.1},
            {
                "110": 14.811504364013672,
                "17": 31.19031302134196,
                "25": 40.099998474121094,
            },
            105_181.85986328125,
        ),
        (
            0.33,
            9.9,
            {"110": 24.9, "17": 99.9, "25": 44.9},
            {
                "110": 14.810107588768005,
                "17": 31.187350908915203,
                "25": 44.900001525878906,
            },
            105_766.09033203125,
        ),
        (
            0.50,
            15.0,
            {"110": 30.0, "17": 105.0, "25": 50.0},
            {
                "110": 14.810977737108866,
                "17": 31.185065587361652,
                "25": 50.0,
            },
            106_437.53466796875,
        ),
    )
    base_cumulative = 104_861.36181640625
    probes = []
    for relative, step, targets, actual, cumulative in points:
        runs = tuple(
            SweepRun(
                relative_amplitude=relative,
                well=well,
                level=Level.HIGH,
                target_m3_per_day=targets[well],
                baseline_rate_m3_per_day=baseline[well],
                actual_m3_per_day=actual[well],
                baseline_cumulative_m3=base_cumulative,
                perturbed_cumulative_m3=cumulative,
            )
            for well in ("110", "17", "25")
        )
        probes.append(build_probe(relative, a_amplitude(step), runs, 0.0409))

    measurement = AmplitudeMeasurement(
        probes=tuple(probes),
        achievability_tolerance=TOLERANCE,
        linearity_tolerance=LINEARITY,
    )

    assert all(p.systematic_shortfall(TOLERANCE) for p in probes)
    assert all(p.distinguishable() for p in probes)
    gains = measurement.gains()
    assert gains[0] == pytest.approx(15.0, abs=0.1)
    assert gains[2] == pytest.approx(63.9, abs=0.1)
    assert measurement.gain_drift()[2] > 3.0
    assert measurement.admissible_probes() == ()
    with pytest.raises(ValueError, match="не замерена"):
        choose_amplitude(measurement)


def test_first_sweep_point_measured_on_model_z_is_rejected_by_achievability() -> None:
    """Первая точка свипа, замеренная настоящими прогонами OPM 16.08.

    Возмущение +17% от медианы (шаг 5.1 м³/сут — нижняя граница приора из
    дека) на трёх скважинах, окно 01.01.2007 + 12 месяцев, 975 с на прогон:

    - 25 добрала цель 40.1 ровно (недобор 0%);
    - 110 при цели 20.1 дала 14.81 — недобор 26%;
    - 17 при цели 95.1 дала 31.19, то есть приёмистость даже упала против
      базовых 31.50 — недобор 67%.

    Две скважины из трёх не добирают, недобор систематический уже на
    минимальной амплитуде приора. Отклик соседей при этом различим
    (+320.5 м³ против порога шума 0.04 м³) — то есть замер ограничивает
    не шум и не нелинейность, а достижимость.
    """

    baseline = {
        "110": 13.89351499080658,
        "17": 31.495544751485188,
        "25": 35.833333333333336,
    }
    targets = {"110": 20.1, "17": 95.1, "25": 40.1}
    actual = {
        "110": 14.811504364013672,
        "17": 31.19031302134196,
        "25": 40.099998474121094,
    }
    step = 5.1
    runs = tuple(
        SweepRun(
            relative_amplitude=0.17,
            well=well,
            level=Level.HIGH,
            target_m3_per_day=targets[well],
            baseline_rate_m3_per_day=baseline[well],
            actual_m3_per_day=actual[well],
            baseline_cumulative_m3=104_861.36,
            perturbed_cumulative_m3=105_181.86,
        )
        for well in ("110", "17", "25")
    )
    probe = build_probe(0.17, a_amplitude(step), runs, 0.0409)

    assert probe.achievability_ok(TOLERANCE) == {
        "110": False,
        "17": False,
        "25": True,
    }
    assert probe.systematic_shortfall(TOLERANCE)
    assert probe.distinguishable()
    assert probe.response_m3 == pytest.approx(961.5, abs=1.0)

    measurement = AmplitudeMeasurement(
        probes=(probe,),
        achievability_tolerance=TOLERANCE,
        linearity_tolerance=LINEARITY,
    )
    with pytest.raises(ValueError, match="не замерена"):
        choose_amplitude(measurement)


def test_largest_still_linear_amplitude_wins() -> None:
    measurement = AmplitudeMeasurement(
        probes=(
            a_probe(0.05, gain=4.0),
            a_probe(0.10, gain=4.0),
            a_probe(0.20, gain=3.9),
            a_probe(0.40, gain=2.0),
        ),
        achievability_tolerance=TOLERANCE,
        linearity_tolerance=LINEARITY,
    )
    verdict = choose_amplitude(measurement)
    assert verdict.relative_amplitude == 0.20
    assert verdict.limited_by == LIMITED_BY_LINEARITY
    assert verdict.breakpoint_relative_amplitude == 0.40


def test_response_below_the_noise_floor_is_not_a_measurement() -> None:
    """Отклик, не отличимый от шума, точку свипа не проходит — амплитуда стоит ниже."""

    louder = a_probe(0.05, gain=4.0, noise=1.0)
    assert louder.distinguishable()
    quiet = a_probe(0.10, gain=4.0, noise=10_000.0)
    assert not quiet.distinguishable()
    measurement = AmplitudeMeasurement(
        probes=(louder, quiet),
        achievability_tolerance=TOLERANCE,
        linearity_tolerance=LINEARITY,
    )
    verdict = choose_amplitude(measurement)
    assert verdict.relative_amplitude == 0.05
    assert verdict.limited_by == LIMITED_BY_NOISE


def test_sweep_that_stays_linear_to_the_top_reports_no_breakpoint() -> None:
    measurement = AmplitudeMeasurement(
        probes=(a_probe(0.05, gain=4.0), a_probe(0.10, gain=4.0)),
        achievability_tolerance=TOLERANCE,
        linearity_tolerance=LINEARITY,
    )
    verdict = choose_amplitude(measurement)
    assert verdict.breakpoint_relative_amplitude is None
    assert verdict.limited_by == LIMITED_BY_SWEEP_RANGE


def test_amplitude_is_never_assigned_when_nothing_passed() -> None:
    """Протокол §8.3: не замерено — значит не назначается вовсе, а не «на глаз»."""

    dead = a_probe(0.05, gain=4.0, noise=10_000.0)
    measurement = AmplitudeMeasurement(
        probes=(dead,),
        achievability_tolerance=TOLERANCE,
        linearity_tolerance=LINEARITY,
    )
    with pytest.raises(ValueError, match="не замерена"):
        choose_amplitude(measurement)


def test_sweep_levels_come_from_the_deck_prior(deck: DeckSchedule) -> None:
    """§8.3: стартовая точка свипа — приор из дека, не выдуманное число."""

    distribution = setpoint_changes(deck, Role.INJ, 146)
    low, high = prior_bracket(distribution, 0.8)
    assert 0.0 < low <= high
    amplitudes = sweep_amplitudes(distribution, (low, high))
    assert len(amplitudes) == 2
    assert amplitudes[0].step_m3_per_day < amplitudes[1].step_m3_per_day
    assert amplitudes[0].base_level_m3_per_day == distribution.median_level_m3_per_day


def test_sweep_levels_must_increase() -> None:
    class _Fake:
        median_level_m3_per_day = 30.0

    with pytest.raises(ValueError):
        sweep_amplitudes(_Fake(), (0.2, 0.1))


def test_noise_floor_is_derived_from_the_data_not_assigned() -> None:
    """Порог различимости выводится из разрешения носителя, а не назначается.

    `UNSMRY` хранит накопления в float32: на объёме порядка 3.4·10⁵ м³ за
    12 месяцев разрешение — около 0.04 м³, то есть численный шум заведомо не
    является связывающим ограничением протокола (замерено на настоящем
    базовом прогоне Model_Z 16.08). Ограничивают линейность и достижимость.
    """

    floor = numerical_noise_floor(342_035.65, safety_factor=1.0)
    assert floor == pytest.approx(0.0408, abs=1e-3)
    assert numerical_noise_floor(342_035.65, safety_factor=10.0) > floor
    with pytest.raises(ValueError):
        numerical_noise_floor(342_035.65, safety_factor=0.5)


def test_probe_selection_rejects_unknown_neighbour_density() -> None:
    with pytest.raises(ValueError):
        ProbeSelection(wells=("A1", "A2", "A9"), neighbour_count=NEIGHBOURS)
