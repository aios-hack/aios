from __future__ import annotations

import pytest

from backend.contexts.reservoir.domain.response import (
    ActiveControlMode,
    IntervalResponse,
    StateAtDate,
)
from backend.contexts.schedule.domain.schedule import (
    Availability,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.constraints.domain.constraints import (
    REGION_PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    SOURCE_ORGANIZER,
    SOURCED_INFRASTRUCTURE_KEYS,
    region_pressure_limits,
    source_key,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_REGION_PRESSURE,
    STATUS_CHECKED,
    STATUS_NOT_SET,
    ViolationKind,
)
from backend.contexts.schedule.domain.validate_dynamic import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
    CONSTRAINT_FIELD_COVERAGE,
    DYNAMIC_VIOLATION_KINDS,
    FIRST_CONTROL_LEVEL_DECK_DATE_INDEX,
    RegionSeries,
    constraint_fields_to_cover,
    level_deck_date_index,
    validate_dynamic,
    verified_constraint_checks,
)

pytestmark = [pytest.mark.slow]

N_INTERVALS: int = 3
BASELINE_PRESSURE_BAR: float = 122.0
DECK_REGIONS: tuple[int, ...] = (1, 2, 3, 4, 5)


def make_schedule(n_intervals: int = N_INTERVALS) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("P1",), n_intervals=n_intervals),
        initial_state={
            "P1": WellState(
                availability=Availability.AVAILABLE,
                role=Role.PROD,
                operating_status=OperatingStatus.OPEN,
                setpoint=50.0,
            )
        },
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


def region_case(
    floor: float | None = None,
    ceiling: float | None = None,
    case_path: str = "config/cases/region-pressure.json",
) -> Constraints:
    infrastructure: dict[str, object] = {}
    if floor is not None:
        infrastructure[REGION_PRESSURE_FLOOR_BAR] = floor
        infrastructure[source_key(REGION_PRESSURE_FLOOR_BAR)] = SOURCE_ORGANIZER
    if ceiling is not None:
        infrastructure[REGION_PRESSURE_CEILING_BAR] = ceiling
        infrastructure[source_key(REGION_PRESSURE_CEILING_BAR)] = SOURCE_ORGANIZER
    return Constraints(infrastructure=infrastructure, case_path=case_path)


def flat_region_series(
    n_intervals: int = N_INTERVALS,
    value: float = BASELINE_PRESSURE_BAR,
    regions: tuple[int, ...] = DECK_REGIONS,
) -> RegionSeries:
    n_dates = FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + n_intervals
    return RegionSeries(
        region_pressure_bar={
            region: tuple(value for _ in range(n_dates)) for region in regions
        }
    )


def region_series_with_outlier(
    region: int,
    control_step: int,
    outlier_bar: float,
    n_intervals: int = N_INTERVALS,
) -> RegionSeries:
    flat = flat_region_series(n_intervals)
    values = list(flat.region_pressure_bar[region])
    values[level_deck_date_index(control_step)] = outlier_bar
    series = dict(flat.region_pressure_bar)
    series[region] = tuple(values)
    return RegionSeries(region_pressure_bar=series)


def report_for(
    constraints: Constraints | None,
    region_series: RegionSeries | None,
    n_intervals: int = N_INTERVALS,
):
    schedule = make_schedule(n_intervals)
    return validate_dynamic(
        schedule,
        full_states(schedule),
        full_intervals(schedule),
        constraints,
        oil_density_t_per_m3=0.85,
        region_series=region_series,
    )


def checks_by_name(report) -> dict[str, object]:
    return {item.constraint: item for item in report.constraint_checks}


REGION_KINDS: frozenset[ViolationKind] = frozenset(
    {
        ViolationKind.REGION_PRESSURE_BELOW_FLOOR,
        ViolationKind.REGION_PRESSURE_ABOVE_CEILING,
    }
)


def region_violations(report) -> tuple:
    return tuple(item for item in report.violations if item.kind in REGION_KINDS)


def test_region_pressure_below_the_floor_names_the_region() -> None:
    series = region_series_with_outlier(region=3, control_step=1, outlier_bar=95.0)
    report = report_for(region_case(floor=100.0), series)

    below = [
        item
        for item in report.violations
        if item.kind is ViolationKind.REGION_PRESSURE_BELOW_FLOOR
    ]
    assert len(below) == 1
    assert below[0].region == 3
    assert below[0].control_step == 1
    assert below[0].value == pytest.approx(95.0)
    assert "region 3" in below[0].detail
    assert "region 3" in str(below[0])


def test_region_pressure_above_the_ceiling_names_the_region() -> None:
    series = region_series_with_outlier(region=5, control_step=2, outlier_bar=260.0)
    report = report_for(region_case(ceiling=200.0), series)

    above = [
        item
        for item in report.violations
        if item.kind is ViolationKind.REGION_PRESSURE_ABOVE_CEILING
    ]
    assert len(above) == 1
    assert above[0].region == 5
    assert above[0].value == pytest.approx(260.0)


def test_region_pressure_inside_the_corridor_gives_no_violation() -> None:
    report = report_for(
        region_case(floor=100.0, ceiling=200.0), flat_region_series()
    )

    kinds = {item.kind for item in report.violations}
    assert ViolationKind.REGION_PRESSURE_BELOW_FLOOR not in kinds
    assert ViolationKind.REGION_PRESSURE_ABOVE_CEILING not in kinds

    check = checks_by_name(report)[CONSTRAINT_REGION_PRESSURE]
    assert check.status == STATUS_CHECKED
    assert check.n_violations == 0
    assert check.blocking
    for region in DECK_REGIONS:
        assert str(region) in check.detail


def test_limits_not_set_means_the_check_is_silent_and_reported_as_not_set() -> None:
    report = report_for(region_case(), None)

    check = checks_by_name(report)[CONSTRAINT_REGION_PRESSURE]
    assert check.status == STATUS_NOT_SET
    assert check.n_violations is None
    assert REGION_PRESSURE_FLOOR_BAR in check.detail
    assert REGION_PRESSURE_CEILING_BAR in check.detail
    assert not region_violations(report)


def test_limits_not_set_stays_silent_even_when_regional_series_arrive() -> None:
    report = report_for(region_case(), flat_region_series(value=10.0))

    check = checks_by_name(report)[CONSTRAINT_REGION_PRESSURE]
    assert check.status == STATUS_NOT_SET
    assert not region_violations(report)


def test_limits_set_without_a_series_is_an_error_not_a_silent_skip() -> None:
    with pytest.raises(ValueError) as error:
        report_for(region_case(floor=100.0), None)

    message = str(error.value)
    assert REGION_PRESSURE_FLOOR_BAR in message
    assert "were not supplied" in message


def test_limits_set_with_an_empty_series_is_an_error() -> None:
    with pytest.raises(ValueError) as error:
        report_for(region_case(floor=100.0), RegionSeries(region_pressure_bar={}))
    assert "are empty" in str(error.value)


def test_series_shorter_than_the_horizon_is_an_error_naming_the_region() -> None:
    short = RegionSeries(
        region_pressure_bar={
            4: tuple(
                BASELINE_PRESSURE_BAR
                for _ in range(FIRST_CONTROL_LEVEL_DECK_DATE_INDEX)
            )
        }
    )
    with pytest.raises(ValueError) as error:
        report_for(region_case(floor=100.0), short)

    message = str(error.value)
    assert "shorter than the horizon" in message
    assert "region 4" in message


def test_every_region_is_compared_on_every_control_step() -> None:
    report = report_for(
        region_case(floor=200.0), flat_region_series(value=BASELINE_PRESSURE_BAR)
    )

    below = [
        item
        for item in report.violations
        if item.kind is ViolationKind.REGION_PRESSURE_BELOW_FLOOR
    ]
    assert len(below) == len(DECK_REGIONS) * N_INTERVALS
    assert {item.region for item in below} == set(DECK_REGIONS)
    assert {item.control_step for item in below} == set(range(N_INTERVALS))


def test_region_pressure_is_declared_in_the_coverage_report() -> None:
    fields = constraint_fields_to_cover()
    assert REGION_PRESSURE_FLOOR_BAR in fields
    assert REGION_PRESSURE_CEILING_BAR in fields
    assert CONSTRAINT_FIELD_COVERAGE[REGION_PRESSURE_FLOOR_BAR] == (
        CONSTRAINT_REGION_PRESSURE,
    )
    assert CONSTRAINT_FIELD_COVERAGE[REGION_PRESSURE_CEILING_BAR] == (
        CONSTRAINT_REGION_PRESSURE,
    )

    report = report_for(region_case(floor=100.0), flat_region_series())
    verified = verified_constraint_checks(report.constraint_checks)
    assert CONSTRAINT_REGION_PRESSURE in {item.constraint for item in verified}


def test_blocking_limits_require_a_declared_source() -> None:
    assert REGION_PRESSURE_FLOOR_BAR in SOURCED_INFRASTRUCTURE_KEYS
    assert REGION_PRESSURE_CEILING_BAR in SOURCED_INFRASTRUCTURE_KEYS
    assert ViolationKind.REGION_PRESSURE_BELOW_FLOOR in (
        BLOCKING_DYNAMIC_VIOLATION_KINDS
    )
    assert ViolationKind.REGION_PRESSURE_ABOVE_CEILING in (
        BLOCKING_DYNAMIC_VIOLATION_KINDS
    )
    assert ViolationKind.REGION_PRESSURE_BELOW_FLOOR in DYNAMIC_VIOLATION_KINDS
    assert ViolationKind.REGION_PRESSURE_ABOVE_CEILING in DYNAMIC_VIOLATION_KINDS


def test_no_default_is_invented_for_either_limit() -> None:
    limits = region_pressure_limits(Constraints())
    assert limits.floor_bar is None
    assert limits.ceiling_bar is None
    assert not limits.enabled


def test_an_empty_region_corridor_is_rejected() -> None:
    with pytest.raises(ValueError) as error:
        region_pressure_limits(region_case(floor=200.0, ceiling=150.0))
    assert "corridor" in str(error.value)
