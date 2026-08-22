from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from backend.infrastructure.opm import OpmDeckEmitter
from backend.infrastructure.opm.dataset_plan import (
    DatasetPlanError,
    PerturbationFamily,
    PlanConfig,
    REQUIRED_FAMILIES,
    baseline_profile,
    build_plan,
    dataset_base_schedule,
    materialize,
)
from backend.core.contracts import EventKind, MAX_LRAT_M3_PER_DAY, Role, Schedule, hash_schedule
from backend.domain.schedule import validate_static

import conftest

MODEL_Z = conftest.model_z_dir()

pytestmark = pytest.mark.skipif(
    MODEL_Z is None, reason=conftest.missing_reason("Model_Z")
)

SEED = 20260816

SMALL = PlanConfig(
    n_level_scenarios=3,
    n_unreachable_scenarios=2,
    n_shutdown_scenarios=2,
    n_conversion_scenarios=2,
)


@pytest.fixture(scope="module")
def base() -> Schedule:
    return dataset_base_schedule(MODEL_Z)


def test_plan_covers_every_required_event_family_without_any_run(base: Schedule) -> None:
    """Приёмка §9.1: план покрывает четыре вида, а не только уровни.

    Проверяется на самом плане, без единого обращения к OPM — дешёвая
    проверка раньше дорогой (§9).
    """

    plan = build_plan(base, seed=SEED, config=SMALL)

    assert REQUIRED_FAMILIES <= plan.families()
    assert all(spec.levels for spec in plan.by_family(PerturbationFamily.LEVELS))
    assert all(
        spec.unreachable for spec in plan.by_family(PerturbationFamily.UNREACHABLE)
    )
    assert all(spec.shutdowns for spec in plan.by_family(PerturbationFamily.SHUTDOWN))
    assert any(
        any(not toggle.enabled for toggle in spec.conversions)
        for spec in plan.by_family(PerturbationFamily.CONVERSION)
    )


def test_plan_rejects_itself_when_a_family_carries_no_perturbation(base: Schedule) -> None:
    """Вид без единого возмущения не считается покрытым — план не строится."""

    with pytest.raises(DatasetPlanError, match="не покрывает"):
        build_plan(
            base,
            seed=SEED,
            config=PlanConfig(
                n_level_scenarios=1,
                n_unreachable_scenarios=0,
                n_shutdown_scenarios=1,
                n_conversion_scenarios=1,
            ),
        )


def test_conversion_retiming_stays_forbidden() -> None:
    """`allow_conversion_retiming = true` запрещён до ответа по §3.11."""

    with pytest.raises(DatasetPlanError, match="allow_conversion_retiming"):
        PlanConfig(allow_conversion_retiming=True)


def test_plan_is_deterministic_for_the_same_seed(base: Schedule) -> None:
    """Тот же seed — тот же план до хеша; другой seed — другой план."""

    first = build_plan(base, seed=SEED, config=SMALL)
    second = build_plan(base, seed=SEED, config=SMALL)
    other = build_plan(base, seed=SEED + 1, config=SMALL)

    assert first.plan_hash == second.plan_hash
    assert first.specs == second.specs
    assert other.plan_hash != first.plan_hash


def test_materialization_is_deterministic_for_the_same_seed(base: Schedule) -> None:
    """Расписания сценариев тоже детерминированы: совпадает canonical_schedule_hash."""

    first = build_plan(base, seed=SEED, config=SMALL)
    second = build_plan(base, seed=SEED, config=SMALL)

    first_hashes = [hash_schedule(materialize(base, spec).schedule) for spec in first]
    second_hashes = [hash_schedule(materialize(base, spec).schedule) for spec in second]

    assert first_hashes == second_hashes
    # Сценарии не вырождены в одно и то же расписание.
    assert len(set(first_hashes)) == len(first_hashes)


def test_baseline_scenario_reproduces_the_base_schedule(base: Schedule) -> None:
    """Опорный сценарий не возмущает ничего — тот же хеш, что у базы."""

    plan = build_plan(base, seed=SEED, config=SMALL)
    (spec,) = plan.by_family(PerturbationFamily.BASELINE)

    assert hash_schedule(materialize(base, spec).schedule) == hash_schedule(base)


def test_every_scenario_passes_static_validation(base: Schedule) -> None:
    """`validate_static == []` до эмита: на невалидный сценарий прогон не тратится."""

    plan = build_plan(base, seed=SEED, config=SMALL)

    for spec in plan:
        report = validate_static(materialize(base, spec).schedule)
        assert report.ok, f"{spec.scenario_id}: {report.format(limit=5)}"


def test_every_scenario_stays_dense_enough_for_the_emitter(base: Schedule) -> None:
    """Плотный слой сохраняется: `OpmDeckEmitter` принимает каждый сценарий."""

    emitter = OpmDeckEmitter(MODEL_Z)
    plan = build_plan(base, seed=SEED, config=SMALL)

    for spec in plan:
        emitter._validate(materialize(base, spec).schedule)


def test_unreachable_targets_exceed_the_wells_own_history(base: Schedule) -> None:
    """Недостижимость — уставка выше исторического максимума, а не флаг (§5.4)."""

    profile = baseline_profile(base)
    plan = build_plan(base, seed=SEED, config=SMALL)

    seen = 0
    for spec in plan.by_family(PerturbationFamily.UNREACHABLE):
        for target in spec.unreachable:
            assert target.setpoint > profile.max_setpoint[target.well]
            assert target.setpoint <= MAX_LRAT_M3_PER_DAY or target.well in profile.injectors
            seen += 1
    assert seen > 0


def test_unreachable_scenarios_report_a_nonzero_fraction(base: Schedule) -> None:
    """Доля недостижимых уставок — метаданное §9.2, а не ноль по умолчанию."""

    plan = build_plan(base, seed=SEED, config=SMALL)

    for spec in plan.by_family(PerturbationFamily.UNREACHABLE):
        assert materialize(base, spec).unreachable_fraction > 0.0
    for spec in plan.by_family(PerturbationFamily.BASELINE):
        assert materialize(base, spec).unreachable_fraction == 0.0


def test_shutdown_scenarios_add_standalone_stops_and_restarts(base: Schedule) -> None:
    """В базе автономных остановок нет — сценарий обязан их создать (§9.1)."""

    plan = build_plan(base, seed=SEED, config=SMALL)
    profile = baseline_profile(base)
    base_shut = sum(1 for event in base.control_events if event.kind is EventKind.SHUT)

    for spec in plan.by_family(PerturbationFamily.SHUTDOWN):
        events = materialize(base, spec).schedule.control_events
        shut = sum(1 for event in events if event.kind is EventKind.SHUT)
        assert shut > base_shut

        for window in spec.shutdowns:
            # Шаг базового перевода из окна исключён: закрыть и тем же шагом
            # открыть нагнетателем — противоречие, а не сценарий.
            conversion = profile.conversion_steps.get(window.well)
            expected = window.to_step - window.from_step
            if conversion is not None and window.from_step <= conversion < window.to_step:
                expected -= 1
            inside = [
                event
                for event in events
                if event.well == window.well
                and window.from_step <= event.control_step < window.to_step
                and event.kind is EventKind.SHUT
                and event.control_step != conversion
            ]
            assert len(inside) == expected
            if window.to_step < base.meta.n_intervals:
                restart = [
                    event
                    for event in events
                    if event.well == window.well
                    and event.control_step == window.to_step
                    and event.kind is EventKind.OPEN
                ]
                assert restart, f"{window.well}: запуска на шаге {window.to_step} нет"


def test_dropped_conversion_keeps_the_well_producing_to_the_end(base: Schedule) -> None:
    """Снятый перевод — событие, а не дыра в плотном слое.

    Скважина остаётся добывающей до конца горизонта: ни одного `SET_RATE`
    после снятой даты, и на каждом шаге есть уставка.
    """

    plan = build_plan(base, seed=SEED, config=SMALL)
    profile = baseline_profile(base)
    checked = 0

    for spec in plan.by_family(PerturbationFamily.CONVERSION):
        events = materialize(base, spec).schedule.control_events
        for toggle in spec.conversions:
            if toggle.enabled:
                continue
            well_events = [event for event in events if event.well == toggle.well]
            assert not any(event.kind is EventKind.CONVERT_INJ for event in well_events)
            assert not any(event.kind is EventKind.SET_RATE for event in well_events)
            steps = {
                event.control_step
                for event in well_events
                if event.kind is EventKind.SET_LRAT
            }
            first = profile.first_controlled_step[toggle.well]
            assert steps == set(range(first, base.meta.n_intervals))
            checked += 1
    assert checked > 0


def test_kept_conversion_keeps_the_base_date(base: Schedule) -> None:
    """Дата перевода не двигается: `allow_conversion_retiming = false` (§9.1)."""

    plan = build_plan(base, seed=SEED, config=SMALL)
    profile = baseline_profile(base)

    for spec in plan.by_family(PerturbationFamily.CONVERSION):
        events = materialize(base, spec).schedule.control_events
        for toggle in spec.conversions:
            assert toggle.control_step == profile.conversion_steps[toggle.well]
            if not toggle.enabled:
                continue
            converted = [
                event.control_step
                for event in events
                if event.well == toggle.well and event.kind is EventKind.CONVERT_INJ
            ]
            assert converted == [toggle.control_step]


def test_level_scenarios_move_setpoints_without_touching_the_ceiling(base: Schedule) -> None:
    """LHS двигает уровни, но потолок Методики не пробивается ни разу."""

    plan = build_plan(base, seed=SEED, config=SMALL)
    base_values = {
        (event.control_step, event.well): event.value
        for event in base.control_events
        if event.kind is EventKind.SET_LRAT
    }

    for spec in plan.by_family(PerturbationFamily.LEVELS):
        events = materialize(base, spec).schedule.control_events
        moved = 0
        for event in events:
            if event.kind is not EventKind.SET_LRAT or event.value is None:
                continue
            assert event.value <= MAX_LRAT_M3_PER_DAY
            original = base_values.get((event.control_step, event.well))
            if original is not None and original != event.value:
                moved += 1
        assert moved > 0


def test_level_factors_are_stratified_across_the_configured_window(base: Schedule) -> None:
    """Латинский гиперкуб: по одному множителю из каждого слоя окна."""

    config = PlanConfig(
        n_level_scenarios=1,
        n_unreachable_scenarios=1,
        n_shutdown_scenarios=1,
        n_conversion_scenarios=1,
        level_wells_fraction=0.4,
    )
    plan = build_plan(base, seed=SEED, config=config)
    (spec,) = plan.by_family(PerturbationFamily.LEVELS)

    factors = sorted(item.factor for item in spec.levels)
    n = len(factors)
    width = (config.level_factor_high - config.level_factor_low) / n
    strata = Counter(
        min(n - 1, int((factor - config.level_factor_low) / width)) for factor in factors
    )

    assert set(strata) == set(range(n))
    assert all(count == 1 for count in strata.values())
    assert factors[0] >= config.level_factor_low
    assert factors[-1] <= config.level_factor_high


def test_fixed_deck_layer_is_never_perturbed(base: Schedule) -> None:
    """§9.1: возмущается управление, а не программа ввода скважин и перфораций."""

    plan = build_plan(base, seed=SEED, config=SMALL)

    for spec in plan:
        material = materialize(base, spec)
        assert tuple(material.schedule.fixed_deck_events) == tuple(base.fixed_deck_events)
        assert material.schedule.initial_state == base.initial_state
        assert tuple(material.schedule.meta.wells) == tuple(base.meta.wells)


def test_conversion_wells_never_receive_lrat_after_a_kept_conversion(base: Schedule) -> None:
    """Роль соблюдается: после сохранённого перевода уставка только SET_RATE."""

    plan = build_plan(base, seed=SEED, config=SMALL)

    for spec in plan:
        material = materialize(base, spec)
        profile = baseline_profile(material.schedule)
        for well in profile.injectors:
            assert profile.max_setpoint[well] >= 0.0
        assert validate_static(material.schedule).ok
