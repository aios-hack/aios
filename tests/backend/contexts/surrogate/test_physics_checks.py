
from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from backend.contexts.schedule.domain.schedule import (
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    N_INTERVALS,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.shared.hashing import hash_schedule
from backend.contexts.surrogate.domain.physics_checks import (
    BhpLimits,
    DEFAULT_OIL_DENSITY_T_PER_M3,
    Invariant,
    PhysicsCheckError,
    PhysicsReport,
    Severity,
    check_pair,
    check_physics,
    check_prediction,
    injection_only_pair,
    lambda_column_sums,
)
from backend.contexts.surrogate.domain.raw_model_output import (
    RawModelOutput,
    RawWellStepPrediction,
)

_WELLS = ("I", "N", "P")
_LATE_OPEN_STEP = 50
_PRODUCER_FLOOR = 50.0
_INJECTOR_CEILING = 300.0

_CLEAN_OIL_MASS = 5.0
_CLEAN_LIQUID = 20.0


def _schedule(
    *,
    injector_setpoint: float = 15.0,
    producer_setpoint: float = 10.0,
    with_deck_limits: bool = True,
) -> Schedule:
    fixed: tuple[FixedDeckEvent, ...] = ()
    if with_deck_limits:
        fixed = (
            FixedDeckEvent(
                control_step=0,
                well="P",
                operator="WCONPROD",
                raw_args=("OPEN", "LRAT", "1*", "1*", "1*", "10.0", "1*", "50", "1*", "1*"),
            ),
            FixedDeckEvent(
                control_step=0,
                well="I",
                operator="WCONINJE",
                raw_args=("WATER", "OPEN", "RATE", "15.0", "1*", "300", "1*", "1*"),
            ),
        )
    return Schedule(
        meta=ScheduleMeta(wells=_WELLS, provenance="test"),
        initial_state={
            "I": WellState(Availability.AVAILABLE, Role.INJ, OperatingStatus.OPEN, injector_setpoint),
            "N": WellState(Availability.NOT_COMMISSIONED, Role.NONE, OperatingStatus.SHUT, 0.0),
            "P": WellState(Availability.AVAILABLE, Role.PROD, OperatingStatus.OPEN, producer_setpoint),
        },
        fixed_deck_events=fixed,
        control_events=(
            ControlEvent(_LATE_OPEN_STEP, "N", EventKind.SET_LRAT, value=5.0),
            ControlEvent(_LATE_OPEN_STEP, "N", EventKind.OPEN),
            ControlEvent(10, "I", EventKind.SET_RATE, value=injector_setpoint),
            ControlEvent(10, "P", EventKind.SET_LRAT, value=producer_setpoint),
        ),
    )


def _node(well: str, step: int, **overrides) -> RawWellStepPrediction:

    commissioned = well != "N" or step >= _LATE_OPEN_STEP
    values: dict[str, object] = dict(well=well, control_step=step)
    if not commissioned:
        values.update(
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=0.0,
            liquid_rate=0.0,
            injection_rate=0.0,
            bhp=120.0,
        )
    elif well == "I":
        values.update(
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=450.0,
            liquid_rate=0.0,
            injection_rate=15.0,
            bhp=250.0,
        )
    else:
        values.update(
            oil_mass_delta=_CLEAN_OIL_MASS,
            liquid_volume_delta=_CLEAN_LIQUID,
            injection_volume_delta=0.0,
            liquid_rate=10.0,
            injection_rate=0.0,
            bhp=80.0,
        )
    values.update(overrides)
    return RawWellStepPrediction(**values)  # type: ignore[arg-type]


def _raw(
    schedule: Schedule,
    overrides: dict[tuple[str, int], RawWellStepPrediction] | None = None,
) -> RawModelOutput:
    overrides = overrides or {}
    nodes = tuple(
        overrides.get((well, step), _node(well, step))
        for well in _WELLS
        for step in range(N_INTERVALS)
    )
    return RawModelOutput(
        canonical_schedule_hash=hash_schedule(schedule), wells=_WELLS, nodes=nodes
    )


def _lambda() -> Lambda:
    return Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2025, 9, 1),
        producers=("N", "P"),
        injectors=("I",),
        matrix=((0.2,), (0.5,)),
        lag_months=0,
        amplitude=1.0,
        stability=1.0,
        rank=1,
        condition_number=1.0,
        achievability_ok={"I": True},
    )




def test_negative_channel_is_refused_by_the_type_before_any_check() -> None:

    with pytest.raises(ValueError, match="is negative"):
        RawWellStepPrediction(
            well="P",
            control_step=0,
            oil_mass_delta=-1.0,
            liquid_volume_delta=_CLEAN_LIQUID,
            injection_volume_delta=0.0,
            liquid_rate=10.0,
            injection_rate=0.0,
            bhp=80.0,
        )




def test_clean_prediction_raises_no_flags() -> None:
    schedule = _schedule()
    report = check_prediction(_raw(schedule), schedule=schedule)

    assert report.counts == {}
    assert report.n_flags == 0
    assert report.n_nodes == len(_WELLS) * N_INTERVALS


def test_single_prediction_report_is_never_complete() -> None:

    schedule = _schedule()
    report = check_prediction(_raw(schedule), schedule=schedule)

    assert report.complete is False
    assert report.admissible is False
    assert set(report.skipped) == {
        Invariant.INJECTION_RESPONSE.value,
        Invariant.MATERIAL_BALANCE.value,
    }




def test_watercut_below_zero_is_flagged() -> None:
    schedule = _schedule()
    poisoned = _node("P", 7, oil_mass_delta=25.0, liquid_volume_delta=_CLEAN_LIQUID)
    report = check_prediction(_raw(schedule, {("P", 7): poisoned}), schedule=schedule)

    assert report.counts == {Invariant.WATERCUT_RANGE.value: 1}
    flag = report.examples[0]
    assert flag.severity is Severity.BLOCKING
    assert flag.well == "P" and flag.control_step == 7
    assert flag.observed < 0.0


def test_oil_without_liquid_is_flagged() -> None:
    schedule = _schedule()
    poisoned = _node("P", 3, oil_mass_delta=1.0, liquid_volume_delta=0.0, liquid_rate=0.0)
    report = check_prediction(_raw(schedule, {("P", 3): poisoned}), schedule=schedule)

    assert report.counts == {Invariant.WATERCUT_RANGE.value: 1}
    assert "is undefined" in report.examples[0].detail


def test_watercut_tolerance_absorbs_unit_conversion_noise() -> None:

    schedule = _schedule()
    liquid = 100.0
    oil_mass = liquid * 1.0005 * DEFAULT_OIL_DENSITY_T_PER_M3
    poisoned = _node("P", 5, oil_mass_delta=oil_mass, liquid_volume_delta=liquid)
    report = check_prediction(_raw(schedule, {("P", 5): poisoned}), schedule=schedule)

    assert report.counts == {}




def test_not_commissioned_well_with_flow_is_flagged() -> None:
    schedule = _schedule()
    poisoned = _node("N", 0, liquid_rate=3.0, liquid_volume_delta=90.0, oil_mass_delta=1.0)
    report = check_prediction(_raw(schedule, {("N", 0): poisoned}), schedule=schedule)

    assert report.counts[Invariant.SHUT_WELL_FLOW.value] == 3
    assert all("not commissioned" in flag.detail for flag in report.examples if flag.invariant is Invariant.SHUT_WELL_FLOW)


def test_commissioned_well_keeps_its_flow() -> None:

    schedule = _schedule()
    report = check_prediction(_raw(schedule), schedule=schedule)

    assert Invariant.SHUT_WELL_FLOW.value not in report.counts




def test_bhp_limits_come_from_the_deck() -> None:
    limits = BhpLimits.from_schedule(_schedule())

    assert limits.producer_default == _PRODUCER_FLOOR
    assert limits.injector_default == _INJECTOR_CEILING
    assert limits.floor_for("P") == _PRODUCER_FLOOR
    assert limits.ceiling_for("I") == _INJECTOR_CEILING


def test_producer_below_floor_is_a_warning_not_a_block() -> None:
    schedule = _schedule()
    poisoned = _node("P", 11, bhp=_PRODUCER_FLOOR - 5.0)
    report = check_prediction(_raw(schedule, {("P", 11): poisoned}), schedule=schedule)

    assert report.counts == {Invariant.BHP_LIMIT.value: 1}
    assert report.blocking_count == 0
    assert report.warning_count == 1
    assert report.examples[0].severity is Severity.WARNING


def test_injector_above_ceiling_is_flagged() -> None:
    schedule = _schedule()
    poisoned = _node("I", 12, bhp=_INJECTOR_CEILING + 10.0)
    report = check_prediction(_raw(schedule, {("I", 12): poisoned}), schedule=schedule)

    assert report.counts == {Invariant.BHP_LIMIT.value: 1}
    assert report.examples[0].limit == _INJECTOR_CEILING


def test_missing_deck_limits_are_skipped_not_passed() -> None:

    schedule = _schedule(with_deck_limits=False)
    report = check_prediction(_raw(schedule), schedule=schedule)

    assert Invariant.BHP_LIMIT.value in report.skipped
    assert Invariant.BHP_LIMIT not in report.evaluated
    assert report.counts == {}




def test_pair_changing_production_is_not_identifiable() -> None:
    reference = _schedule()
    candidate = _schedule(producer_setpoint=12.0)
    identifiable, reason = injection_only_pair(reference, candidate)

    assert identifiable is False
    assert EventKind.SET_LRAT.value in reason


def test_pair_changing_only_injection_is_identifiable() -> None:
    reference = _schedule()
    candidate = _schedule(injector_setpoint=16.0)

    assert injection_only_pair(reference, candidate) == (True, "")


def test_unidentifiable_pair_skips_both_differential_invariants() -> None:
    reference_schedule = _schedule()
    candidate_schedule = _schedule(producer_setpoint=12.0)
    report = check_pair(
        _raw(reference_schedule),
        _raw(candidate_schedule),
        reference_schedule=reference_schedule,
        candidate_schedule=candidate_schedule,
        lam=_lambda(),
    )

    assert report.evaluated == ()
    assert set(report.skipped) == {
        Invariant.INJECTION_RESPONSE.value,
        Invariant.MATERIAL_BALANCE.value,
    }




def test_injection_up_and_liquid_down_is_flagged() -> None:
    reference_schedule = _schedule()
    candidate_schedule = _schedule(injector_setpoint=16.0)
    reference = _raw(reference_schedule)
    candidate = _raw(
        candidate_schedule,
        {
            ("I", step): _node("I", step, injection_volume_delta=500.0)
            for step in range(N_INTERVALS)
        }
        | {
            ("P", step): _node("P", step, liquid_volume_delta=1.0, oil_mass_delta=0.5)
            for step in range(N_INTERVALS)
        },
    )
    report = check_pair(
        reference,
        candidate,
        reference_schedule=reference_schedule,
        candidate_schedule=candidate_schedule,
        lam=_lambda(),
    )

    assert report.counts[Invariant.INJECTION_RESPONSE.value] == 1
    assert report.examples[0].well == "I"


def test_clean_pair_raises_no_differential_flags() -> None:
    reference_schedule = _schedule()
    candidate_schedule = _schedule(injector_setpoint=16.0)
    candidate = _raw(
        candidate_schedule,
        {
            ("I", step): _node("I", step, injection_volume_delta=500.0)
            for step in range(N_INTERVALS)
        }
        | {
            ("P", step): _node("P", step, liquid_volume_delta=25.0)
            for step in range(N_INTERVALS)
        },
    )
    report = check_pair(
        _raw(reference_schedule),
        candidate,
        reference_schedule=reference_schedule,
        candidate_schedule=candidate_schedule,
        lam=_lambda(),
    )

    assert report.counts == {}
    assert set(report.evaluated) == {
        Invariant.INJECTION_RESPONSE,
        Invariant.MATERIAL_BALANCE,
    }




def test_water_from_nowhere_is_flagged() -> None:

    reference_schedule = _schedule()
    candidate_schedule = _schedule(injector_setpoint=16.0)
    candidate = _raw(
        candidate_schedule,
        {
            ("I", step): _node("I", step, injection_volume_delta=451.0)
            for step in range(N_INTERVALS)
        }
        | {
            ("P", step): _node("P", step, liquid_volume_delta=2_000.0)
            for step in range(N_INTERVALS)
        },
    )
    report = check_pair(
        _raw(reference_schedule),
        candidate,
        reference_schedule=reference_schedule,
        candidate_schedule=candidate_schedule,
        lam=_lambda(),
    )

    assert report.counts[Invariant.MATERIAL_BALANCE.value] == 1
    assert report.examples[-1].well == "<field>"


def test_material_balance_counts_water_not_liquid() -> None:

    reference_schedule = _schedule()
    candidate_schedule = _schedule(injector_setpoint=16.0)
    candidate = _raw(
        candidate_schedule,
        {
            ("I", step): _node("I", step, injection_volume_delta=451.0)
            for step in range(N_INTERVALS)
        }
        | {
            ("P", step): _node(
                "P",
                step,
                liquid_volume_delta=_CLEAN_LIQUID + 100.0,
                oil_mass_delta=(_CLEAN_LIQUID + 100.0 - (_CLEAN_LIQUID - _CLEAN_OIL_MASS / DEFAULT_OIL_DENSITY_T_PER_M3))
                * DEFAULT_OIL_DENSITY_T_PER_M3,
            )
            for step in range(N_INTERVALS)
        },
    )
    report = check_pair(
        _raw(reference_schedule),
        candidate,
        reference_schedule=reference_schedule,
        candidate_schedule=candidate_schedule,
        lam=_lambda(),
    )

    assert Invariant.MATERIAL_BALANCE.value not in report.counts




def test_lambda_column_sums_are_reported_not_enforced() -> None:

    sums = lambda_column_sums(_lambda())

    assert sums == {"I": pytest.approx(0.7)}




def test_check_physics_without_reference_is_incomplete_and_inadmissible() -> None:
    schedule = _schedule()
    report = check_physics(_raw(schedule), schedule=schedule, lam=_lambda())

    assert report.complete is False
    assert report.admissible is False
    assert "the reference was not supplied" in report.skipped[Invariant.INJECTION_RESPONSE.value]


def test_check_physics_with_reference_covers_all_seven() -> None:
    reference_schedule = _schedule()
    candidate_schedule = _schedule(injector_setpoint=16.0)
    candidate = _raw(
        candidate_schedule,
        {
            ("I", step): _node("I", step, injection_volume_delta=500.0)
            for step in range(N_INTERVALS)
        },
    )
    report = check_physics(
        candidate,
        schedule=candidate_schedule,
        reference=_raw(reference_schedule),
        reference_schedule=reference_schedule,
        lam=_lambda(),
    )

    assert set(report.evaluated) == set(Invariant)
    assert report.skipped == {}
    assert report.complete is True
    assert report.admissible is True


def test_blocking_flag_makes_candidate_inadmissible() -> None:
    reference_schedule = _schedule()
    candidate_schedule = _schedule(injector_setpoint=16.0)
    candidate = _raw(
        candidate_schedule,
        {("P", 4): _node("P", 4, oil_mass_delta=25.0)}
        | {
            ("I", step): _node("I", step, injection_volume_delta=500.0)
            for step in range(N_INTERVALS)
        },
    )
    report = check_physics(
        candidate,
        schedule=candidate_schedule,
        reference=_raw(reference_schedule),
        reference_schedule=reference_schedule,
        lam=_lambda(),
    )

    assert report.complete is True
    assert report.blocking_count == 1
    assert report.admissible is False


def test_warning_alone_keeps_candidate_admissible() -> None:
    reference_schedule = _schedule()
    candidate_schedule = _schedule(injector_setpoint=16.0)
    candidate = _raw(
        candidate_schedule,
        {("P", 4): _node("P", 4, bhp=_PRODUCER_FLOOR - 1.0)}
        | {
            ("I", step): _node("I", step, injection_volume_delta=500.0)
            for step in range(N_INTERVALS)
        },
    )
    report = check_physics(
        candidate,
        schedule=candidate_schedule,
        reference=_raw(reference_schedule),
        reference_schedule=reference_schedule,
        lam=_lambda(),
    )

    assert report.warning_count == 1
    assert report.blocking_count == 0
    assert report.admissible is True




def test_counts_are_complete_while_examples_are_capped() -> None:
    schedule = _schedule()
    overrides = {
        ("P", step): _node("P", step, oil_mass_delta=25.0) for step in range(N_INTERVALS)
    }
    report = check_prediction(
        _raw(schedule, overrides), schedule=schedule, max_examples=3
    )

    assert report.counts[Invariant.WATERCUT_RANGE.value] == N_INTERVALS
    assert len(report.examples) == 3


def test_report_refuses_invariant_both_evaluated_and_skipped() -> None:
    with pytest.raises(PhysicsCheckError, match="simultaneously"):
        PhysicsReport(
            counts={},
            examples=(),
            evaluated=(Invariant.BHP_LIMIT,),
            skipped={Invariant.BHP_LIMIT.value: "reason"},
            n_nodes=1,
            n_wells=1,
        )


def test_pair_refuses_identical_schedules() -> None:
    schedule = _schedule()
    with pytest.raises(PhysicsCheckError, match="one and the same schedule"):
        check_pair(
            _raw(schedule),
            _raw(schedule),
            reference_schedule=schedule,
            candidate_schedule=schedule,
            lam=_lambda(),
        )


def test_prediction_refuses_foreign_well_axis() -> None:
    schedule = _schedule()
    other = replace(schedule, meta=ScheduleMeta(wells=("I", "N"), provenance="test"))
    with pytest.raises(PhysicsCheckError, match="wells axis"):
        check_prediction(_raw(schedule), schedule=other)


def test_report_serialises_to_json_ready_dict() -> None:
    schedule = _schedule()
    report = check_prediction(
        _raw(schedule, {("P", 1): _node("P", 1, oil_mass_delta=25.0)}), schedule=schedule
    )
    payload = report.as_dict()

    assert payload["format"] == "aios.surrogate-physics-report.v1"
    assert payload["blocking_count"] == 1
    assert payload["examples"][0]["invariant"] == Invariant.WATERCUT_RANGE.value
