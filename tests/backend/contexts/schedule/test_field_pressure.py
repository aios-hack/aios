from __future__ import annotations

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
    WellState,
)
from backend.contexts.constraints.domain.constraints import (
    PRESSURE_CEILING_BAR,
    PRESSURE_FLOOR_BAR,
    SOURCE_ORGANIZER,
    field_pressure_limits,
    source_key,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_FIELD_PRESSURE,
    CONSTRAINT_MATERIAL_BALANCE,
    STATUS_CHECKED,
    STATUS_NOT_SET,
    ViolationKind,
)
from backend.contexts.schedule.domain.validate_dynamic import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
    DYNAMIC_VIOLATION_KINDS,
    FIRST_CONTROL_LEVEL_DECK_DATE_INDEX,
    MATERIAL_BALANCE_RELATIVE_TOLERANCE,
    FieldSeries,
    control_step_of_level,
    level_deck_date_index,
    validate_dynamic,
)

pytestmark = [pytest.mark.slow]

N_INTERVALS: int = 3
BASELINE_PRESSURE_BAR: float = 122.0


def producer(setpoint: float = 50.0) -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.OPEN,
        setpoint=setpoint,
    )


def make_schedule(n_intervals: int = N_INTERVALS) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("P1",), n_intervals=n_intervals),
        initial_state={"P1": producer()},
        fixed_deck_events=(),
        control_events=(),
    )


def full_states(schedule: Schedule) -> tuple[StateAtDate, ...]:
    n_dates = FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + schedule.meta.n_intervals
    return tuple(
        StateAtDate(
            deck_date_index=index,
            well=well,
            liquid_rate=0.0,
            oil_rate=0.0,
            injection_rate=0.0,
            thp=20.0,
            bhp=120.0,
            well_efficiency=1.0,
            active_control_mode=ActiveControlMode.RATE_TARGET,
        )
        for well in schedule.meta.wells
        for index in range(n_dates)
    )


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


def pressure_case(
    floor: float | None = None,
    ceiling: float | None = None,
    case_path: str = "config/cases/pressure.json",
) -> Constraints:
    infrastructure: dict[str, object] = {}
    if floor is not None:
        infrastructure[PRESSURE_FLOOR_BAR] = floor
        infrastructure[source_key(PRESSURE_FLOOR_BAR)] = SOURCE_ORGANIZER
    if ceiling is not None:
        infrastructure[PRESSURE_CEILING_BAR] = ceiling
        infrastructure[source_key(PRESSURE_CEILING_BAR)] = SOURCE_ORGANIZER
    return Constraints(infrastructure=infrastructure, case_path=case_path)


def flat_pressure_series(
    n_intervals: int = N_INTERVALS, value: float = BASELINE_PRESSURE_BAR
) -> FieldSeries:
    n_dates = FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + n_intervals
    return FieldSeries(field_pressure_bar=tuple(value for _ in range(n_dates)))


def pressure_series_with_outlier(
    control_step: int,
    outlier_bar: float,
    n_intervals: int = N_INTERVALS,
) -> FieldSeries:
    n_dates = FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + n_intervals
    values = [BASELINE_PRESSURE_BAR for _ in range(n_dates)]
    values[level_deck_date_index(control_step)] = outlier_bar
    return FieldSeries(field_pressure_bar=tuple(values))


def healthy_balance_series(n_intervals: int = N_INTERVALS) -> FieldSeries:
    n_dates = FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + n_intervals
    flat = flat_pressure_series(n_intervals)
    oil_produced = tuple(float(index) * 10.0 for index in range(n_dates))
    water_produced = tuple(float(index) * 4.0 for index in range(n_dates))
    water_injected = tuple(float(index) * 9.0 for index in range(n_dates))
    oil_in_place = tuple(1.0e6 - value for value in oil_produced)
    water_in_place = tuple(
        2.0e6 + injected - produced
        for injected, produced in zip(water_injected, water_produced)
    )
    return FieldSeries(
        field_pressure_bar=flat.field_pressure_bar,
        oil_produced_cum_m3=oil_produced,
        water_produced_cum_m3=water_produced,
        water_injected_cum_m3=water_injected,
        oil_in_place_m3=oil_in_place,
        water_in_place_m3=water_in_place,
    )


def broken_balance_series(n_intervals: int = N_INTERVALS) -> FieldSeries:
    healthy = healthy_balance_series(n_intervals)
    corrupted = list(healthy.oil_in_place_m3)
    corrupted[-1] = corrupted[-1] - 0.5 * healthy.oil_produced_cum_m3[-1]
    return FieldSeries(
        field_pressure_bar=healthy.field_pressure_bar,
        oil_produced_cum_m3=healthy.oil_produced_cum_m3,
        water_produced_cum_m3=healthy.water_produced_cum_m3,
        water_injected_cum_m3=healthy.water_injected_cum_m3,
        oil_in_place_m3=tuple(corrupted),
        water_in_place_m3=healthy.water_in_place_m3,
    )


def report_for(
    constraints: Constraints | None,
    field_series: FieldSeries | None,
    n_intervals: int = N_INTERVALS,
):
    schedule = make_schedule(n_intervals)
    return validate_dynamic(
        schedule,
        full_states(schedule),
        full_intervals(schedule),
        constraints,
        oil_density_t_per_m3=0.85,
        field_series=field_series,
    )


def checks_by_name(report) -> dict[str, object]:
    return {item.constraint: item for item in report.constraint_checks}


def test_axis_projection_reads_levels_one_step_after_the_deck_date() -> None:
    assert FIRST_CONTROL_LEVEL_DECK_DATE_INDEX == 147
    assert level_deck_date_index(0) == 147
    assert control_step_of_level(147) == 0
    for control_step in range(N_INTERVALS):
        assert control_step_of_level(level_deck_date_index(control_step)) == (
            control_step
        )


def test_pressure_policy_without_a_series_is_an_error_not_a_silent_skip() -> None:
    with pytest.raises(ValueError) as error:
        report_for(pressure_case(floor=100.0), None)
    message = str(error.value)
    assert PRESSURE_FLOOR_BAR in message
    assert "не передана" in message


def test_pressure_policy_with_an_empty_series_is_an_error() -> None:
    with pytest.raises(ValueError) as error:
        report_for(pressure_case(floor=100.0), FieldSeries(field_pressure_bar=()))
    assert "пуста" in str(error.value)


def test_pressure_series_shorter_than_the_horizon_is_an_error() -> None:
    short = FieldSeries(
        field_pressure_bar=tuple(
            BASELINE_PRESSURE_BAR
            for _ in range(FIRST_CONTROL_LEVEL_DECK_DATE_INDEX)
        )
    )
    with pytest.raises(ValueError) as error:
        report_for(pressure_case(floor=100.0), short)
    assert "короче горизонта" in str(error.value)


def test_pressure_below_the_floor_is_a_violation() -> None:
    series = pressure_series_with_outlier(1, 95.0)
    report = report_for(pressure_case(floor=100.0), series)
    below = [
        item
        for item in report.violations
        if item.kind is ViolationKind.FIELD_PRESSURE_BELOW_FLOOR
    ]
    assert len(below) == 1
    assert below[0].value == pytest.approx(95.0)


def test_pressure_above_the_ceiling_is_a_violation() -> None:
    series = pressure_series_with_outlier(2, 260.0)
    report = report_for(pressure_case(ceiling=200.0), series)
    above = [
        item
        for item in report.violations
        if item.kind is ViolationKind.FIELD_PRESSURE_ABOVE_CEILING
    ]
    assert len(above) == 1
    assert above[0].value == pytest.approx(260.0)


def test_pressure_inside_the_corridor_gives_no_violation() -> None:
    report = report_for(
        pressure_case(floor=100.0, ceiling=200.0), flat_pressure_series()
    )
    kinds = {item.kind for item in report.violations}
    assert ViolationKind.FIELD_PRESSURE_BELOW_FLOOR not in kinds
    assert ViolationKind.FIELD_PRESSURE_ABOVE_CEILING not in kinds
    check = checks_by_name(report)[CONSTRAINT_FIELD_PRESSURE]
    assert check.status == STATUS_CHECKED
    assert check.n_violations == 0
    assert check.blocking


@pytest.mark.parametrize("control_step", range(N_INTERVALS))
def test_violation_names_the_control_step_of_the_offending_deck_date(
    control_step: int,
) -> None:
    series = pressure_series_with_outlier(control_step, 95.0)
    report = report_for(pressure_case(floor=100.0), series)
    steps = [
        item.control_step
        for item in report.violations
        if item.kind is ViolationKind.FIELD_PRESSURE_BELOW_FLOOR
    ]
    assert steps == [control_step]


def test_a_one_step_shift_of_the_projection_would_be_caught() -> None:
    outlier_deck_date_index = 148
    expected_control_step = 1
    n_dates = 150
    values = [BASELINE_PRESSURE_BAR for _ in range(n_dates)]
    values[outlier_deck_date_index] = 95.0
    series = FieldSeries(field_pressure_bar=tuple(values))
    report = report_for(pressure_case(floor=100.0), series)
    reported = [
        item.control_step
        for item in report.violations
        if item.kind is ViolationKind.FIELD_PRESSURE_BELOW_FLOOR
    ]
    assert reported == [expected_control_step]
    assert reported != [expected_control_step - 1]
    assert reported != [expected_control_step + 1]


def test_limit_not_set_means_the_check_does_not_run() -> None:
    report = report_for(Constraints(), flat_pressure_series())
    check = checks_by_name(report)[CONSTRAINT_FIELD_PRESSURE]
    assert check.status == STATUS_NOT_SET
    assert check.n_violations is None
    assert PRESSURE_FLOOR_BAR in check.detail
    assert PRESSURE_CEILING_BAR in check.detail
    kinds = {item.kind for item in report.violations}
    assert ViolationKind.FIELD_PRESSURE_BELOW_FLOOR not in kinds
    assert ViolationKind.FIELD_PRESSURE_ABOVE_CEILING not in kinds


def test_no_limit_means_no_error_even_without_a_series() -> None:
    report = report_for(Constraints(), None)
    assert checks_by_name(report)[CONSTRAINT_FIELD_PRESSURE].status == (
        STATUS_NOT_SET
    )


def test_violation_text_names_the_limit_field_source_and_case() -> None:
    series = pressure_series_with_outlier(0, 95.0)
    report = report_for(
        pressure_case(floor=100.0, case_path="config/cases/pressure.json"), series
    )
    detail = next(
        item.detail
        for item in report.violations
        if item.kind is ViolationKind.FIELD_PRESSURE_BELOW_FLOOR
    )
    assert f"infrastructure.{PRESSURE_FLOOR_BAR}" in detail
    assert SOURCE_ORGANIZER in detail
    assert "условие организаторов" in detail
    assert "config/cases/pressure.json" in detail


def test_pressure_kinds_are_blocking_and_declared_dynamic() -> None:
    for kind in (
        ViolationKind.FIELD_PRESSURE_BELOW_FLOOR,
        ViolationKind.FIELD_PRESSURE_ABOVE_CEILING,
    ):
        assert kind in DYNAMIC_VIOLATION_KINDS
        assert kind in BLOCKING_DYNAMIC_VIOLATION_KINDS


def test_pressure_check_makes_the_report_reject_the_schedule() -> None:
    series = pressure_series_with_outlier(0, 95.0)
    report = report_for(pressure_case(floor=100.0), series)
    assert not report.blocking_ok


def test_empty_pressure_corridor_is_refused_by_the_contract() -> None:
    constraints = pressure_case(floor=200.0, ceiling=150.0)
    with pytest.raises(ValueError) as error:
        field_pressure_limits(constraints)
    assert PRESSURE_CEILING_BAR in str(error.value)


def test_healthy_material_balance_gives_no_violation() -> None:
    report = report_for(Constraints(), healthy_balance_series())
    kinds = {item.kind for item in report.violations}
    assert ViolationKind.MATERIAL_BALANCE_BROKEN not in kinds
    check = checks_by_name(report)[CONSTRAINT_MATERIAL_BALANCE]
    assert check.status == STATUS_CHECKED
    assert check.n_violations == 0


def test_broken_material_balance_is_a_violation() -> None:
    report = report_for(Constraints(), broken_balance_series())
    broken = [
        item
        for item in report.violations
        if item.kind is ViolationKind.MATERIAL_BALANCE_BROKEN
    ]
    assert broken
    assert broken[0].value > MATERIAL_BALANCE_RELATIVE_TOLERANCE
    assert str(MATERIAL_BALANCE_RELATIVE_TOLERANCE) in broken[0].detail


def test_material_balance_without_series_is_reported_as_not_set() -> None:
    report = report_for(Constraints(), None)
    check = checks_by_name(report)[CONSTRAINT_MATERIAL_BALANCE]
    assert check.status == STATUS_NOT_SET
    assert check.n_violations is None


def test_material_balance_is_reported_even_without_a_case() -> None:
    report = report_for(None, healthy_balance_series())
    check = checks_by_name(report)[CONSTRAINT_MATERIAL_BALANCE]
    assert check.status == STATUS_CHECKED


def test_pressure_and_balance_run_together_from_one_series() -> None:
    series = healthy_balance_series()
    corrupted = FieldSeries(
        field_pressure_bar=pressure_series_with_outlier(
            2, 95.0
        ).field_pressure_bar,
        oil_produced_cum_m3=series.oil_produced_cum_m3,
        water_produced_cum_m3=series.water_produced_cum_m3,
        water_injected_cum_m3=series.water_injected_cum_m3,
        oil_in_place_m3=series.oil_in_place_m3,
        water_in_place_m3=series.water_in_place_m3,
    )
    report = report_for(pressure_case(floor=100.0), corrupted)
    names = checks_by_name(report)
    assert names[CONSTRAINT_FIELD_PRESSURE].status == STATUS_CHECKED
    assert names[CONSTRAINT_MATERIAL_BALANCE].status == STATUS_CHECKED
    assert [
        item.control_step
        for item in report.violations
        if item.kind is ViolationKind.FIELD_PRESSURE_BELOW_FLOOR
    ] == [2]
