from __future__ import annotations

import importlib

import pytest

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
    WellOutage,
    WellState,
)
from backend.core.contracts.constraints import (
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    COMPENSATION_SCOPE,
    EXTERNAL_WATER_M3_PER_DAY,
    WATER_REINJECTION_FRACTION,
    WATER_SUPPLY_UNLIMITED,
)
from backend.domain.schedule.validate import (
    CONSTRAINT_BHP_LIMITS,
    CONSTRAINT_COMPENSATION,
    CONSTRAINT_COMPENSATION_SCOPE,
    CONSTRAINT_INJECTION_LIMITS,
    CONSTRAINT_LIQUID_LIMITS,
    CONSTRAINT_PRODUCTION_FLOORS,
    CONSTRAINT_WATER_SUPPLY,
    CONSTRAINT_WATERCUT_LIMITS,
    CONSTRAINT_WELL_OUTAGES,
    CONSTRAINT_WELL_OUTAGES_STATIC,
    STATUS_CHECKED,
    STATUS_NOT_SET,
    STATUS_UNSUPPORTED,
    STATUS_WAIVED,
    ConstraintCheck,
    ViolationKind,
    check_constraints,
)
from backend.domain.schedule.validate_dynamic import (
    CONSTRAINT_FIELD_COVERAGE,
    FIRST_CONTROL_DECK_DATE_INDEX,
    PHYSICS_CONSTRAINT_NAMES,
    PROVENANCE_FIELDS,
    constraint_fields_to_cover,
    constraint_kinds,
    validate_dynamic,
    verified_constraint_checks,
)

OIL_DENSITY_T_PER_M3: float = 0.85


def producer(setpoint: float = 50.0) -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.OPEN,
        setpoint=setpoint,
    )


def make_schedule(n_intervals: int = 3) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("P1",), n_intervals=n_intervals),
        initial_state={"P1": producer()},
        fixed_deck_events=(),
        control_events=(),
    )


def full_states(
    schedule: Schedule,
    *,
    liquid_rate: float = 0.0,
    oil_rate: float = 0.0,
    injection_rate: float = 0.0,
) -> tuple[StateAtDate, ...]:
    result: list[StateAtDate] = []
    n_dates = schedule.meta.n_intervals + FIRST_CONTROL_DECK_DATE_INDEX + 1
    for well in schedule.meta.wells:
        for index in range(n_dates):
            result.append(
                StateAtDate(
                    deck_date_index=index,
                    well=well,
                    liquid_rate=liquid_rate,
                    oil_rate=oil_rate,
                    injection_rate=injection_rate,
                    thp=20.0,
                    bhp=120.0,
                    well_efficiency=1.0,
                    active_control_mode=ActiveControlMode.RATE_TARGET,
                )
            )
    return tuple(result)


def full_intervals(
    schedule: Schedule,
    *,
    oil: float = 0.0,
    liquid: float = 0.0,
    injection: float = 0.0,
) -> tuple[IntervalResponse, ...]:
    return tuple(
        IntervalResponse(
            control_step=step,
            well=well,
            oil_mass_delta=oil,
            liquid_volume_delta=liquid,
            injection_volume_delta=injection,
        )
        for well in schedule.meta.wells
        for step in range(schedule.meta.n_intervals)
    )


def report_for(
    constraints: Constraints | None,
    *,
    liquid_rate: float = 0.0,
    oil_rate: float = 0.0,
    liquid: float = 0.0,
    oil: float = 0.0,
    injection: float = 0.0,
):
    schedule = make_schedule()
    return validate_dynamic(
        schedule,
        full_states(schedule, liquid_rate=liquid_rate, oil_rate=oil_rate),
        full_intervals(schedule, oil=oil, liquid=liquid, injection=injection),
        constraints,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )


def by_name(checks: tuple[ConstraintCheck, ...]) -> dict[str, ConstraintCheck]:
    return {item.constraint: item for item in checks}


def test_every_constraints_field_gets_a_record_in_the_report() -> None:
    report = report_for(Constraints())
    present = {item.constraint for item in report.constraint_checks}

    missing: list[str] = []
    for field_name in constraint_fields_to_cover():
        expected = CONSTRAINT_FIELD_COVERAGE.get(field_name)
        if expected is None or not present.issuperset(expected):
            missing.append(field_name)

    assert not missing, (
        "поля кейса без записи в отчёте о применённых ограничениях: "
        f"{sorted(missing)}"
    )


def test_coverage_map_names_only_declared_constraints() -> None:
    report = report_for(Constraints())
    present = {item.constraint for item in report.constraint_checks}
    named = {
        name for names in CONSTRAINT_FIELD_COVERAGE.values() for name in names
    } | set(PHYSICS_CONSTRAINT_NAMES)

    assert named == present


def test_a_new_constraints_field_without_a_record_fails_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = report_for(Constraints()).constraint_checks
    module = importlib.import_module(
        "backend.domain.schedule.validate_dynamic"
    )
    monkeypatch.setattr(
        module,
        "constraint_fields_to_cover",
        lambda: constraint_fields_to_cover() + ("gas_limits",),
    )

    with pytest.raises(ValueError, match="gas_limits"):
        verified_constraint_checks(checks)


def test_the_field_list_follows_the_constraints_dataclass() -> None:
    covered = constraint_fields_to_cover()

    for name in Constraints.__dataclass_fields__:
        if name in PROVENANCE_FIELDS:
            continue
        assert name in covered, (
            f"поле {name} объявлено в Constraints, но не попало в список "
            "полей, требующих записи в отчёте"
        )


def test_a_field_missing_from_the_coverage_map_fails_the_report() -> None:
    report = report_for(Constraints())
    checks = report.constraint_checks
    original = dict(CONSTRAINT_FIELD_COVERAGE)
    CONSTRAINT_FIELD_COVERAGE.pop("watercut_limits")
    try:
        with pytest.raises(ValueError, match="watercut_limits"):
            verified_constraint_checks(checks)
    finally:
        CONSTRAINT_FIELD_COVERAGE.clear()
        CONSTRAINT_FIELD_COVERAGE.update(original)


def test_repeated_records_for_one_constraint_are_rejected() -> None:
    report = report_for(Constraints())
    doubled = report.constraint_checks + (report.constraint_checks[0],)

    with pytest.raises(ValueError, match="повторяющиеся"):
        verified_constraint_checks(doubled)


def test_unset_fields_are_not_set_rather_than_silently_clean() -> None:
    report = report_for(Constraints())
    checks = by_name(report.constraint_checks)

    for name in (
        CONSTRAINT_LIQUID_LIMITS,
        CONSTRAINT_INJECTION_LIMITS,
        CONSTRAINT_PRODUCTION_FLOORS,
        CONSTRAINT_WATERCUT_LIMITS,
        CONSTRAINT_WELL_OUTAGES,
        CONSTRAINT_WELL_OUTAGES_STATIC,
        CONSTRAINT_WATER_SUPPLY,
        CONSTRAINT_COMPENSATION,
    ):
        assert checks[name].status == STATUS_NOT_SET
        assert checks[name].n_violations is None


def test_checked_field_carries_the_number_of_violations() -> None:
    constraints = Constraints(liquid_limits={2007: 10.0})
    report = report_for(constraints, liquid_rate=100.0)
    check = by_name(report.constraint_checks)[CONSTRAINT_LIQUID_LIMITS]

    assert check.status == STATUS_CHECKED
    assert check.blocking is True
    assert check.kinds == (ViolationKind.LIQUID_LIMIT_EXCEEDED,)
    assert check.n_violations == report.counts()[
        ViolationKind.LIQUID_LIMIT_EXCEEDED
    ]
    assert check.n_violations == 3


def test_checked_field_without_violations_is_zero_not_absent() -> None:
    constraints = Constraints(liquid_limits={2007: 10_000.0})
    report = report_for(constraints, liquid_rate=1.0)
    check = by_name(report.constraint_checks)[CONSTRAINT_LIQUID_LIMITS]

    assert check.status == STATUS_CHECKED
    assert check.n_violations == 0


def test_one_rate_field_set_leaves_the_other_two_not_set() -> None:
    report = report_for(Constraints(injection_limits={2007: 5.0}))
    checks = by_name(report.constraint_checks)

    assert checks[CONSTRAINT_INJECTION_LIMITS].status == STATUS_CHECKED
    assert checks[CONSTRAINT_LIQUID_LIMITS].status == STATUS_NOT_SET
    assert checks[CONSTRAINT_PRODUCTION_FLOORS].status == STATUS_NOT_SET


def test_outages_are_reported_by_both_the_static_and_the_dynamic_check() -> None:
    constraints = Constraints(well_outages=(WellOutage("P1", 0, 1),))
    report = report_for(constraints, liquid_rate=7.0)
    checks = by_name(report.constraint_checks)

    assert checks[CONSTRAINT_WELL_OUTAGES].status == STATUS_CHECKED
    assert checks[CONSTRAINT_WELL_OUTAGES].n_violations == 2
    assert checks[CONSTRAINT_WELL_OUTAGES_STATIC].status == STATUS_CHECKED
    assert checks[CONSTRAINT_WELL_OUTAGES_STATIC].n_violations == 0
    assert checks[CONSTRAINT_WELL_OUTAGES_STATIC].kinds == (
        ViolationKind.WELL_OUTAGE_VIOLATED,
    )


def test_compensation_scope_groups_is_unsupported_not_checked() -> None:
    constraints = Constraints(
        infrastructure={
            COMPENSATION_MIN: 0.5,
            COMPENSATION_MAX: 1.5,
            COMPENSATION_SCOPE: "groups",
        }
    )
    report = report_for(constraints, liquid=100.0, injection=100.0)
    checks = by_name(report.constraint_checks)

    scope = checks[CONSTRAINT_COMPENSATION_SCOPE]
    assert scope.status == STATUS_UNSUPPORTED
    assert scope.n_violations is None
    assert "groups" in scope.detail
    assert checks[CONSTRAINT_COMPENSATION].status == STATUS_CHECKED


def test_compensation_scope_field_and_groups_is_unsupported_too() -> None:
    constraints = Constraints(
        infrastructure={
            COMPENSATION_MIN: 0.5,
            COMPENSATION_MAX: 1.5,
            COMPENSATION_SCOPE: "field_and_groups",
        }
    )
    report = report_for(constraints, liquid=100.0, injection=100.0)
    checks = by_name(report.constraint_checks)

    assert checks[CONSTRAINT_COMPENSATION_SCOPE].status == STATUS_UNSUPPORTED


def test_compensation_scope_field_is_the_only_supported_value() -> None:
    constraints = Constraints(
        infrastructure={
            COMPENSATION_MIN: 0.5,
            COMPENSATION_MAX: 1.5,
            COMPENSATION_SCOPE: "field",
        }
    )
    report = report_for(constraints, liquid=100.0, injection=100.0)
    checks = by_name(report.constraint_checks)

    assert checks[CONSTRAINT_COMPENSATION_SCOPE].status == STATUS_CHECKED
    assert checks[CONSTRAINT_COMPENSATION_SCOPE].n_violations == 0


def test_compensation_carries_the_enforcement_mode() -> None:
    constraints = Constraints(
        infrastructure={
            COMPENSATION_MIN: 0.5,
            COMPENSATION_MAX: 1.5,
            COMPENSATION_ENFORCEMENT: "hard",
            COMPENSATION_SCOPE: "field",
        }
    )
    report = report_for(constraints, liquid=100.0, injection=10.0)
    check = by_name(report.constraint_checks)[CONSTRAINT_COMPENSATION]

    assert check.enforcement == "hard"
    assert check.blocking is True
    assert check.n_violations == 3


def test_diagnostic_compensation_is_checked_but_not_blocking() -> None:
    constraints = Constraints(
        infrastructure={
            COMPENSATION_MIN: 0.5,
            COMPENSATION_MAX: 1.5,
            COMPENSATION_SCOPE: "field",
        }
    )
    report = report_for(constraints, liquid=100.0, injection=10.0)
    check = by_name(report.constraint_checks)[CONSTRAINT_COMPENSATION]

    assert check.status == STATUS_CHECKED
    assert check.enforcement == "diagnostic"
    assert check.blocking is False


def test_unlimited_water_supply_is_waived_not_unset() -> None:
    constraints = Constraints(infrastructure={WATER_SUPPLY_UNLIMITED: True})
    report = report_for(constraints, injection=1_000_000.0)
    check = by_name(report.constraint_checks)[CONSTRAINT_WATER_SUPPLY]

    assert check.status == STATUS_WAIVED
    assert check.status != STATUS_NOT_SET
    assert check.n_violations is None
    assert WATER_SUPPLY_UNLIMITED in check.detail


def test_water_supply_with_a_source_is_checked() -> None:
    constraints = Constraints(
        infrastructure={
            WATER_REINJECTION_FRACTION: 1.0,
            EXTERNAL_WATER_M3_PER_DAY: 0.0,
        }
    )
    report = report_for(constraints, liquid=10.0, oil=8.5, injection=1000.0)
    check = by_name(report.constraint_checks)[CONSTRAINT_WATER_SUPPLY]

    assert check.status == STATUS_CHECKED
    assert check.blocking is True
    assert check.n_violations == 3


def test_watercut_limits_are_checked_when_set() -> None:
    constraints = Constraints(watercut_limits={2007: 0.1})
    report = report_for(constraints, liquid=100.0, oil=8.5)
    check = by_name(report.constraint_checks)[CONSTRAINT_WATERCUT_LIMITS]

    assert check.status == STATUS_CHECKED
    assert check.n_violations == 3


def test_absent_constraints_still_produce_a_complete_report() -> None:
    report = report_for(None)
    checks = by_name(report.constraint_checks)

    assert all(
        item.status == STATUS_NOT_SET
        for name, item in checks.items()
        if name != CONSTRAINT_BHP_LIMITS
    )
    assert len(checks) == len(report.constraint_checks)


def test_bhp_corridor_is_checked_even_without_a_case() -> None:
    check = by_name(report_for(None).constraint_checks)[CONSTRAINT_BHP_LIMITS]

    assert check.status == STATUS_CHECKED
    assert check.blocking
    assert "50.0" in check.detail
    assert "300.0" in check.detail
    assert "organizer" in check.detail


def test_checks_are_sorted_by_constraint_name() -> None:
    report = report_for(Constraints())
    names = [item.constraint for item in report.constraint_checks]

    assert names == sorted(names)


def test_checked_status_demands_a_number_of_violations() -> None:
    with pytest.raises(ValueError, match="число нарушений"):
        ConstraintCheck(
            constraint=CONSTRAINT_LIQUID_LIMITS,
            status=STATUS_CHECKED,
            kinds=(ViolationKind.LIQUID_LIMIT_EXCEEDED,),
            n_violations=None,
            blocking=True,
            enforcement=None,
            detail="проверено",
        )


def test_unchecked_status_refuses_a_number_of_violations() -> None:
    with pytest.raises(ValueError, match="не выполнялась"):
        ConstraintCheck(
            constraint=CONSTRAINT_LIQUID_LIMITS,
            status=STATUS_NOT_SET,
            kinds=(ViolationKind.LIQUID_LIMIT_EXCEEDED,),
            n_violations=0,
            blocking=True,
            enforcement=None,
            detail="не задано",
        )


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="неизвестный статус"):
        ConstraintCheck(
            constraint=CONSTRAINT_LIQUID_LIMITS,
            status="probably_fine",
            kinds=(),
            n_violations=None,
            blocking=False,
            enforcement=None,
            detail="",
        )


def test_constraint_kinds_refuses_an_undeclared_constraint() -> None:
    with pytest.raises(KeyError, match="gas_limits"):
        constraint_kinds("gas_limits")


def test_static_check_reports_its_own_status_next_to_the_violations() -> None:
    constraints = Constraints(well_outages=(WellOutage("P1", 0, 1),))
    violations, check = check_constraints((), constraints)

    assert violations == ()
    assert check.constraint == CONSTRAINT_WELL_OUTAGES_STATIC
    assert check.status == STATUS_CHECKED
    assert check.n_violations == 0


def test_static_check_without_outages_is_not_set() -> None:
    violations, check = check_constraints((), Constraints())

    assert violations == ()
    assert check.status == STATUS_NOT_SET
    assert check.n_violations is None


def test_check_as_dict_is_json_ready() -> None:
    report = report_for(Constraints(liquid_limits={2007: 1.0}))
    document = by_name(report.constraint_checks)[CONSTRAINT_LIQUID_LIMITS].as_dict()

    assert document["constraint"] == CONSTRAINT_LIQUID_LIMITS
    assert document["status"] == STATUS_CHECKED
    assert document["kinds"] == ["LIQUID_LIMIT_EXCEEDED"]
    assert isinstance(document["n_violations"], int)
    assert isinstance(document["blocking"], bool)
    assert isinstance(document["detail"], str)
