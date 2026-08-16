from __future__ import annotations

import pytest

from connectivity import (
    LIMITED_BY_ACHIEVABILITY,
    LIMITED_BY_LINEARITY,
    LIMITED_BY_NOISE,
    LIMITED_BY_SWEEP_RANGE,
    Amplitude,
    AmplitudeMeasurement,
    DeckSchedule,
    Level,
    ProbeSelection,
    build_probe,
    choose_amplitude,
    demote_plan_amplitude,
    prior_bracket,
    select_probe_injectors,
    setpoint_changes,
    sweep_amplitudes,
    SweepRun,
)
from contracts import Role

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


def test_probe_selection_rejects_unknown_neighbour_density() -> None:
    with pytest.raises(ValueError):
        ProbeSelection(wells=("A1", "A2", "A9"), neighbour_count=NEIGHBOURS)
