from __future__ import annotations

import pytest

from backend.core.contracts import (
    ActiveControlMode,
    Availability,
    Constraints,
    Groups,
    IntervalResponse,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    WellState,
)
from backend.contexts.constraints.domain.constraints import (
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    COMPENSATION_SCOPE,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_COMPENSATION,
    CONSTRAINT_COMPENSATION_SCOPE,
    STATUS_CHECKED,
    STATUS_NOT_SET,
    ConstraintCheck,
    ViolationKind,
)
from backend.contexts.schedule.domain.validate_dynamic import (
    FIRST_CONTROL_DECK_DATE_INDEX,
    DynamicReport,
    validate_dynamic,
)

pytestmark = [pytest.mark.slow]

WELLS: tuple[str, ...] = ("P1", "I1", "P2", "I2")
N_INTERVALS: int = 2


def producer() -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.OPEN,
        setpoint=50.0,
    )


def injector() -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.INJ,
        operating_status=OperatingStatus.OPEN,
        setpoint=50.0,
    )


def make_schedule() -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=WELLS, n_intervals=N_INTERVALS),
        initial_state={
            "P1": producer(),
            "I1": injector(),
            "P2": producer(),
            "I2": injector(),
        },
        fixed_deck_events=(),
        control_events=(),
    )


def states_for(schedule: Schedule) -> tuple[StateAtDate, ...]:
    n_dates = schedule.meta.n_intervals + FIRST_CONTROL_DECK_DATE_INDEX + 1
    rates = {
        "P1": (50.0, 0.0),
        "P2": (50.0, 0.0),
        "I1": (0.0, 50.0),
        "I2": (0.0, 50.0),
    }
    return tuple(
        StateAtDate(
            deck_date_index=index,
            well=well,
            liquid_rate=rates[well][0],
            oil_rate=0.0,
            injection_rate=rates[well][1],
            thp=20.0,
            bhp=120.0,
            well_efficiency=1.0,
            active_control_mode=ActiveControlMode.RATE_TARGET,
        )
        for well in schedule.meta.wells
        for index in range(n_dates)
    )


def intervals_for(
    volumes: dict[str, tuple[float, float]],
) -> tuple[IntervalResponse, ...]:
    return tuple(
        IntervalResponse(
            control_step=step,
            well=well,
            oil_mass_delta=0.0,
            liquid_volume_delta=volumes[well][0],
            injection_volume_delta=volumes[well][1],
        )
        for well in WELLS
        for step in range(N_INTERVALS)
    )


def two_groups() -> Groups:
    return Groups(
        groups={"G1": ("I1", "P1"), "G2": ("I2", "P2")},
        lambda_hash="lambda-test",
        group_hash="group-test",
    )


def constraints_with(scope: str, enforcement: str = "diagnostic") -> Constraints:
    return Constraints(
        infrastructure={
            COMPENSATION_MIN: 0.9,
            COMPENSATION_MAX: 1.1,
            COMPENSATION_ENFORCEMENT: enforcement,
            COMPENSATION_SCOPE: scope,
        }
    )


def skewed_volumes() -> dict[str, tuple[float, float]]:
    return {
        "P1": (100.0, 0.0),
        "I1": (0.0, 40.0),
        "P2": (100.0, 0.0),
        "I2": (0.0, 160.0),
    }


def balanced_volumes() -> dict[str, tuple[float, float]]:
    return {
        "P1": (100.0, 0.0),
        "I1": (0.0, 100.0),
        "P2": (100.0, 0.0),
        "I2": (0.0, 100.0),
    }


def report_for(
    scope: str,
    volumes: dict[str, tuple[float, float]],
    *,
    groups: Groups | None = None,
    enforcement: str = "diagnostic",
) -> DynamicReport:
    schedule = make_schedule()
    return validate_dynamic(
        schedule,
        states_for(schedule),
        intervals_for(volumes),
        constraints_with(scope, enforcement),
        groups=groups,
    )


def by_name(checks: tuple[ConstraintCheck, ...]) -> dict[str, ConstraintCheck]:
    return {item.constraint: item for item in checks}


def compensation_violations(report: DynamicReport) -> tuple[str, ...]:
    return tuple(
        item.detail
        for item in report.violations
        if item.kind
        in (
            ViolationKind.COMPENSATION_OUT_OF_CORRIDOR,
            ViolationKind.COMPENSATION_UNDEFINED,
        )
    )


def test_field_scope_produces_no_group_violations() -> None:
    report = report_for("field", skewed_volumes(), groups=two_groups())
    details = compensation_violations(report)

    assert details == ()
    assert not any("участок" in text for text in details)
    checks = by_name(report.constraint_checks)
    assert checks[CONSTRAINT_COMPENSATION].status == STATUS_CHECKED
    assert checks[CONSTRAINT_COMPENSATION].n_violations == 0
    assert checks[CONSTRAINT_COMPENSATION_SCOPE].status == STATUS_CHECKED
    assert checks[CONSTRAINT_COMPENSATION_SCOPE].n_violations == 0


def test_group_scope_catches_a_skew_the_field_total_hides() -> None:
    field_only = report_for("field", skewed_volumes(), groups=two_groups())
    assert compensation_violations(field_only) == ()

    report = report_for("groups", skewed_volumes(), groups=two_groups())
    offenders = [
        item
        for item in report.violations
        if item.kind is ViolationKind.COMPENSATION_OUT_OF_CORRIDOR
    ]

    assert len(offenders) == 2 * N_INTERVALS
    assert all("участок" in item.detail for item in offenders)
    assert {item.control_step for item in offenders} == set(range(N_INTERVALS))
    named = {
        "G1" if "G1" in item.detail else "G2" for item in offenders
    }
    assert named == {"G1", "G2"}


def test_group_scope_alone_does_not_report_the_field_cut() -> None:
    report = report_for("groups", skewed_volumes(), groups=two_groups())
    checks = by_name(report.constraint_checks)

    assert checks[CONSTRAINT_COMPENSATION].status == STATUS_NOT_SET
    assert checks[CONSTRAINT_COMPENSATION].n_violations is None
    assert checks[CONSTRAINT_COMPENSATION_SCOPE].status == STATUS_CHECKED
    assert checks[CONSTRAINT_COMPENSATION_SCOPE].n_violations == 2 * N_INTERVALS


def test_field_and_groups_catches_both_cuts() -> None:
    volumes = {
        "P1": (100.0, 0.0),
        "I1": (0.0, 10.0),
        "P2": (100.0, 0.0),
        "I2": (0.0, 10.0),
    }
    report = report_for("field_and_groups", volumes, groups=two_groups())
    details = compensation_violations(report)
    checks = by_name(report.constraint_checks)

    assert checks[CONSTRAINT_COMPENSATION].status == STATUS_CHECKED
    assert checks[CONSTRAINT_COMPENSATION].n_violations == N_INTERVALS
    assert checks[CONSTRAINT_COMPENSATION_SCOPE].status == STATUS_CHECKED
    assert checks[CONSTRAINT_COMPENSATION_SCOPE].n_violations == 2 * N_INTERVALS
    assert sum(1 for text in details if "поле целиком" in text) == N_INTERVALS
    assert sum(1 for text in details if "участок" in text) == 2 * N_INTERVALS


def test_group_scope_without_groups_is_an_error_not_a_skip() -> None:
    with pytest.raises(ValueError, match="Groups"):
        report_for("groups", balanced_volumes())


def test_field_and_groups_without_groups_is_an_error_too() -> None:
    with pytest.raises(ValueError, match="Groups"):
        report_for("field_and_groups", balanced_volumes())


def test_field_scope_without_groups_stays_allowed() -> None:
    report = report_for("field", balanced_volumes())

    assert compensation_violations(report) == ()


def test_compensation_scope_is_checked_not_unsupported() -> None:
    for scope in ("groups", "field_and_groups"):
        report = report_for(scope, balanced_volumes(), groups=two_groups())
        check = by_name(report.constraint_checks)[CONSTRAINT_COMPENSATION_SCOPE]

        assert check.status == STATUS_CHECKED
        assert check.n_violations == 0
        assert "group-test" in check.detail


def test_zero_group_withdrawal_is_undefined_not_a_fake_ratio() -> None:
    volumes = {
        "P1": (100.0, 0.0),
        "I1": (0.0, 100.0),
        "P2": (0.0, 0.0),
        "I2": (0.0, 5.0),
    }
    report = report_for("groups", volumes, groups=two_groups())
    undefined = [
        item
        for item in report.violations
        if item.kind is ViolationKind.COMPENSATION_UNDEFINED
    ]

    assert len(undefined) == N_INTERVALS
    assert all("G2" in item.detail for item in undefined)
    assert all(item.value == 5.0 for item in undefined)
    assert all("не определена" in item.detail for item in undefined)


def test_group_violations_block_only_under_hard_enforcement() -> None:
    soft = report_for(
        "groups", skewed_volumes(), groups=two_groups(), enforcement="diagnostic"
    )
    hard = report_for(
        "groups", skewed_volumes(), groups=two_groups(), enforcement="hard"
    )

    assert soft.blocking_ok
    assert not hard.blocking_ok
    assert by_name(hard.constraint_checks)[
        CONSTRAINT_COMPENSATION_SCOPE
    ].blocking is True


def test_a_well_outside_every_group_is_an_error() -> None:
    partial = Groups(
        groups={"G1": ("I1", "P1")},
        lambda_hash="lambda-test",
        group_hash="group-partial",
    )

    with pytest.raises(ValueError, match="P2"):
        report_for("groups", balanced_volumes(), groups=partial)
