from __future__ import annotations

from backend.core.contracts import (
    ActiveControlMode,
    Availability,
    Constraints,
    IntervalResponse,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    WellState,
    canonical_bytes,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_OIL_LIMITS,
    CONSTRAINT_PRODUCTION_FLOORS,
    STATUS_CHECKED,
    STATUS_NOT_SET,
    ConstraintCheck,
    ViolationKind,
)
from backend.contexts.schedule.domain.validate_dynamic import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
    CONSTRAINT_FIELD_COVERAGE,
    DYNAMIC_VIOLATION_KINDS,
    FIRST_CONTROL_DECK_DATE_INDEX,
    constraint_fields_to_cover,
    constraint_kinds,
    validate_dynamic,
    verified_constraint_checks,
)

OIL_DENSITY_T_PER_M3: float = 0.85
N_STEPS: int = 3


def producer(setpoint: float = 50.0) -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.OPEN,
        setpoint=setpoint,
    )


def make_schedule(n_intervals: int = N_STEPS) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("P1",), n_intervals=n_intervals),
        initial_state={"P1": producer()},
        fixed_deck_events=(),
        control_events=(),
    )


def states_with_oil(
    schedule: Schedule, oil_by_step: dict[int, float]
) -> tuple[StateAtDate, ...]:
    n_dates = schedule.meta.n_intervals + FIRST_CONTROL_DECK_DATE_INDEX + 1
    result: list[StateAtDate] = []
    for well in schedule.meta.wells:
        for index in range(n_dates):
            step = index - FIRST_CONTROL_DECK_DATE_INDEX - 1
            oil = oil_by_step.get(step, 0.0)
            result.append(
                StateAtDate(
                    deck_date_index=index,
                    well=well,
                    liquid_rate=oil,
                    oil_rate=oil,
                    injection_rate=0.0,
                    thp=20.0,
                    bhp=120.0,
                    well_efficiency=1.0,
                    active_control_mode=ActiveControlMode.RATE_TARGET,
                )
            )
    return tuple(result)


def full_intervals(schedule: Schedule) -> tuple[IntervalResponse, ...]:
    return tuple(
        IntervalResponse(
            control_step=step,
            well=well,
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=0.0,
        )
        for well in schedule.meta.wells
        for step in range(schedule.meta.n_intervals)
    )


def report_for(
    constraints: Constraints, oil_by_step: dict[int, float] | None = None
):
    schedule = make_schedule()
    return validate_dynamic(
        schedule,
        states_with_oil(schedule, oil_by_step or {}),
        full_intervals(schedule),
        constraints,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )


def by_name(checks: tuple[ConstraintCheck, ...]) -> dict[str, ConstraintCheck]:
    return {item.constraint: item for item in checks}


def test_oil_limit_exceeded_on_one_step_names_that_step() -> None:
    report = report_for(
        Constraints(oil_limits={2007: 100.0}),
        {0: 50.0, 1: 140.0, 2: 90.0},
    )

    violations = [
        item
        for item in report.violations
        if item.kind is ViolationKind.OIL_LIMIT_EXCEEDED
    ]

    assert len(violations) == 1
    assert violations[0].control_step == 1
    assert violations[0].value == 140.0
    assert "100.0" in violations[0].detail
    assert "2007" in violations[0].detail


def test_oil_limit_at_the_ceiling_is_not_a_violation() -> None:
    report = report_for(
        Constraints(oil_limits={2007: 100.0}), {0: 100.0, 1: 100.0, 2: 100.0}
    )

    assert not [
        item
        for item in report.violations
        if item.kind is ViolationKind.OIL_LIMIT_EXCEEDED
    ]


def test_oil_limit_is_a_step_rate_not_a_yearly_sum() -> None:
    under_every_step = report_for(
        Constraints(oil_limits={2007: 100.0}), {0: 90.0, 1: 90.0, 2: 90.0}
    )
    over_one_step = report_for(
        Constraints(oil_limits={2007: 100.0}), {0: 0.0, 1: 101.0, 2: 0.0}
    )

    assert not [
        item
        for item in under_every_step.violations
        if item.kind is ViolationKind.OIL_LIMIT_EXCEEDED
    ]
    assert [
        item.control_step
        for item in over_one_step.violations
        if item.kind is ViolationKind.OIL_LIMIT_EXCEEDED
    ] == [1]


def test_oil_limit_violation_blocks_the_schedule() -> None:
    report = report_for(Constraints(oil_limits={2007: 10.0}), {0: 20.0})

    assert ViolationKind.OIL_LIMIT_EXCEEDED in BLOCKING_DYNAMIC_VIOLATION_KINDS
    assert ViolationKind.OIL_LIMIT_EXCEEDED in DYNAMIC_VIOLATION_KINDS
    assert not report.blocking_ok
    assert ViolationKind.OIL_LIMIT_EXCEEDED in {
        item.kind for item in report.blocking_violations
    }


def test_oil_limits_has_a_record_in_the_coverage_report() -> None:
    assert "oil_limits" in constraint_fields_to_cover()
    assert CONSTRAINT_FIELD_COVERAGE["oil_limits"] == (CONSTRAINT_OIL_LIMITS,)
    assert constraint_kinds(CONSTRAINT_OIL_LIMITS) == (
        ViolationKind.OIL_LIMIT_EXCEEDED,
    )

    checks = by_name(report_for(Constraints()).constraint_checks)

    assert checks[CONSTRAINT_OIL_LIMITS].status == STATUS_NOT_SET
    assert checks[CONSTRAINT_OIL_LIMITS].n_violations is None
    assert checks[CONSTRAINT_OIL_LIMITS].blocking is False


def test_declared_oil_limits_report_checked_with_a_count() -> None:
    report = report_for(Constraints(oil_limits={2007: 10.0}), {0: 20.0, 1: 30.0})
    check = by_name(report.constraint_checks)[CONSTRAINT_OIL_LIMITS]

    assert check.status == STATUS_CHECKED
    assert check.n_violations == 2
    assert check.blocking is True
    assert "2007" in check.detail


def test_coverage_guard_accepts_the_report_with_oil_limits() -> None:
    checks = report_for(Constraints(oil_limits={2007: 10.0})).constraint_checks

    verified = verified_constraint_checks(checks)

    assert CONSTRAINT_OIL_LIMITS in {item.constraint for item in verified}


def test_floor_and_ceiling_on_one_year_are_separate_violations() -> None:
    report = report_for(
        Constraints(production_floors={2007: 50.0}, oil_limits={2007: 100.0}),
        {0: 10.0, 1: 75.0, 2: 200.0},
    )
    kinds = {(item.control_step, item.kind) for item in report.violations}

    assert (0, ViolationKind.PRODUCTION_FLOOR_MISSED) in kinds
    assert (2, ViolationKind.OIL_LIMIT_EXCEEDED) in kinds
    assert (1, ViolationKind.PRODUCTION_FLOOR_MISSED) not in kinds
    assert (1, ViolationKind.OIL_LIMIT_EXCEEDED) not in kinds

    checks = by_name(report.constraint_checks)

    assert checks[CONSTRAINT_PRODUCTION_FLOORS].n_violations == 1
    assert checks[CONSTRAINT_OIL_LIMITS].n_violations == 1


def test_dynamic_report_serializes_and_the_hash_repeats() -> None:
    report = report_for(Constraints(oil_limits={2007: 10.0}), {0: 20.0})

    first = canonical_bytes(report)
    second = canonical_bytes(report)

    assert first == second
    assert b'"OIL_LIMIT_EXCEEDED"' in first


def test_blocking_kinds_of_the_report_are_an_ordered_tuple() -> None:
    report = report_for(Constraints())

    assert isinstance(report.blocking_kinds, tuple)
    assert list(report.blocking_kinds) == sorted(
        report.blocking_kinds, key=lambda kind: kind.value
    )
    assert set(report.blocking_kinds) == set(BLOCKING_DYNAMIC_VIOLATION_KINDS)
