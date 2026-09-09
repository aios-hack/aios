from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.contracts import (
    Availability,
    Constraints,
    IntervalResponse,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    ActiveControlMode,
    WellState,
)
from backend.core.contracts.constraints import (
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    COMPENSATION_SCOPE,
)
from backend.domain.schedule.validate import (
    CONSTRAINT_COMPENSATION,
    ViolationKind,
)
from backend.domain.schedule.validate_dynamic import (
    COMPENSATION_RESERVOIR_CONDITIONS,
    COMPENSATION_SURFACE_CONDITIONS,
    COMPENSATION_SURFACE_NOTICE,
    FIRST_CONTROL_DECK_DATE_INDEX,
    FIRST_CONTROL_LEVEL_DECK_DATE_INDEX,
    DynamicReport,
    control_step_pressures,
    reservoir_step_totals,
    validate_dynamic,
)
from tools.compensation_range import (
    CompensationRangeError,
    build_artifact,
    compensation_range,
    distribution_of,
)

WELLS: tuple[str, ...] = ("P1", "I1")
N_INTERVALS: int = 2
OIL_DENSITY_T_PER_M3: float = 0.9


def make_schedule() -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=WELLS, n_intervals=N_INTERVALS),
        initial_state={
            "P1": WellState(
                availability=Availability.AVAILABLE,
                role=Role.PROD,
                operating_status=OperatingStatus.OPEN,
                setpoint=50.0,
            ),
            "I1": WellState(
                availability=Availability.AVAILABLE,
                role=Role.INJ,
                operating_status=OperatingStatus.OPEN,
                setpoint=50.0,
            ),
        },
        fixed_deck_events=(),
        control_events=(),
    )


def states_for(schedule: Schedule) -> tuple[StateAtDate, ...]:
    n_dates = schedule.meta.n_intervals + FIRST_CONTROL_DECK_DATE_INDEX + 1
    rates = {"P1": (50.0, 0.0), "I1": (0.0, 50.0)}
    states: list[StateAtDate] = []
    for deck_date_index in range(n_dates):
        for well in WELLS:
            liquid, injection = rates[well]
            states.append(
                StateAtDate(
                    deck_date_index=deck_date_index,
                    well=well,
                    liquid_rate=liquid,
                    oil_rate=liquid * OIL_DENSITY_T_PER_M3,
                    injection_rate=injection,
                    thp=0.0,
                    bhp=120.0,
                    well_efficiency=1.0,
                    active_control_mode=ActiveControlMode.RATE_TARGET,
                )
            )
    return tuple(states)


def intervals(
    liquid: float, oil_mass: float, injection: float
) -> tuple[IntervalResponse, ...]:
    rows: list[IntervalResponse] = []
    for control_step in range(N_INTERVALS):
        rows.append(
            IntervalResponse(
                control_step=control_step,
                well="P1",
                oil_mass_delta=oil_mass,
                liquid_volume_delta=liquid,
                injection_volume_delta=0.0,
            )
        )
        rows.append(
            IntervalResponse(
                control_step=control_step,
                well="I1",
                oil_mass_delta=0.0,
                liquid_volume_delta=0.0,
                injection_volume_delta=injection,
            )
        )
    return tuple(rows)


def constraints_with(minimum: float, maximum: float) -> Constraints:
    return Constraints(
        infrastructure={
            COMPENSATION_MIN: minimum,
            COMPENSATION_MAX: maximum,
            COMPENSATION_ENFORCEMENT: "diagnostic",
            COMPENSATION_SCOPE: "field",
        }
    )


def report_for(
    interval_responses: tuple[IntervalResponse, ...],
    minimum: float,
    maximum: float,
    reservoir_factors: tuple[tuple[float, float], ...] | None = None,
) -> DynamicReport:
    schedule = make_schedule()
    return validate_dynamic(
        schedule,
        states_for(schedule),
        interval_responses,
        constraints_with(minimum, maximum),
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
        report_undershoot=False,
        reservoir_factors=reservoir_factors,
    )


def compensation_check(report: DynamicReport):
    for item in report.constraint_checks:
        if item.constraint == CONSTRAINT_COMPENSATION:
            return item
    raise AssertionError("в отчёте нет записи о коридоре компенсации")


def test_tool_refuses_without_response(tmp_path: Path) -> None:
    missing = tmp_path / "response.json"
    with pytest.raises(CompensationRangeError) as error:
        build_artifact(missing)
    assert str(missing) in str(error.value)
    assert not list(tmp_path.iterdir())


def test_tool_refuses_empty_response() -> None:
    with pytest.raises(CompensationRangeError):
        compensation_range(())


def test_distribution_matches_hand_computed_values() -> None:
    rows: list[IntervalResponse] = []
    values = (1.0, 2.0, 3.0, 4.0, 5.0)
    for control_step, injection in enumerate(values):
        rows.append(
            IntervalResponse(
                control_step=control_step,
                well="P1",
                oil_mass_delta=0.0,
                liquid_volume_delta=100.0,
                injection_volume_delta=0.0,
            )
        )
        rows.append(
            IntervalResponse(
                control_step=control_step,
                well="I1",
                oil_mass_delta=0.0,
                liquid_volume_delta=0.0,
                injection_volume_delta=injection * 100.0,
            )
        )
    measured = compensation_range(tuple(rows))
    assert tuple(step.value for step in measured.steps) == values
    distribution = measured.distribution
    assert distribution.minimum == pytest.approx(1.0)
    assert distribution.maximum == pytest.approx(5.0)
    assert distribution.median == pytest.approx(3.0)
    assert distribution.p05 == pytest.approx(1.2)
    assert distribution.p95 == pytest.approx(4.8)
    assert distribution.mean == pytest.approx(3.0)
    assert distribution.n_steps == 5


def test_negative_deltas_are_clipped_like_the_validator() -> None:
    rows = (
        IntervalResponse(
            control_step=0,
            well="P1",
            oil_mass_delta=0.0,
            liquid_volume_delta=100.0,
            injection_volume_delta=0.0,
        ),
        IntervalResponse(
            control_step=0,
            well="P2",
            oil_mass_delta=0.0,
            liquid_volume_delta=-40.0,
            injection_volume_delta=0.0,
        ),
        IntervalResponse(
            control_step=0,
            well="I1",
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=120.0,
        ),
        IntervalResponse(
            control_step=0,
            well="I2",
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=-20.0,
        ),
    )
    measured = compensation_range(rows)
    assert measured.steps[0].value == pytest.approx(1.2)


def test_by_year_split_follows_t0() -> None:
    rows: list[IntervalResponse] = []
    for control_step in range(13):
        injection = 100.0 if control_step < 12 else 200.0
        rows.append(
            IntervalResponse(
                control_step=control_step,
                well="P1",
                oil_mass_delta=0.0,
                liquid_volume_delta=100.0,
                injection_volume_delta=0.0,
            )
        )
        rows.append(
            IntervalResponse(
                control_step=control_step,
                well="I1",
                oil_mass_delta=0.0,
                liquid_volume_delta=0.0,
                injection_volume_delta=injection,
            )
        )
    measured = compensation_range(tuple(rows))
    by_year = dict(measured.by_year)
    assert sorted(by_year) == [2007, 2008]
    assert by_year[2007].n_steps == 12
    assert by_year[2007].median == pytest.approx(1.0)
    assert by_year[2008].n_steps == 1
    assert by_year[2008].median == pytest.approx(2.0)


def test_distribution_of_rejects_empty() -> None:
    with pytest.raises(CompensationRangeError):
        distribution_of(())


def test_reservoir_conversion_on_known_factors() -> None:
    oil_mass = 45.0
    liquid = 100.0
    injection = 120.0
    oil_factor = 1.2
    water_factor = 1.05
    withdrawal, injected = reservoir_step_totals(
        oil_mass,
        liquid,
        injection,
        OIL_DENSITY_T_PER_M3,
        oil_factor,
        water_factor,
    )
    oil_volume = oil_mass / OIL_DENSITY_T_PER_M3
    water_volume = liquid - oil_volume
    assert oil_volume == pytest.approx(50.0)
    assert water_volume == pytest.approx(50.0)
    assert withdrawal == pytest.approx(50.0 * 1.2 + 50.0 * 1.05)
    assert withdrawal == pytest.approx(112.5)
    assert injected == pytest.approx(126.0)
    assert injected / withdrawal == pytest.approx(1.12)


def test_validator_uses_reservoir_factors_when_given() -> None:
    rows = intervals(liquid=100.0, oil_mass=45.0, injection=120.0)
    factors = ((1.2, 1.05),) * N_INTERVALS
    surface = report_for(rows, 1.19, 1.21)
    assert not surface.violations
    assert compensation_check(surface).detail.count(
        COMPENSATION_SURFACE_CONDITIONS
    )
    reservoir = report_for(rows, 1.19, 1.21, factors)
    out_of_corridor = [
        item
        for item in reservoir.violations
        if item.kind is ViolationKind.COMPENSATION_OUT_OF_CORRIDOR
    ]
    assert len(out_of_corridor) == N_INTERVALS
    assert out_of_corridor[0].value == pytest.approx(1.12)
    assert COMPENSATION_RESERVOIR_CONDITIONS in out_of_corridor[0].detail
    assert COMPENSATION_RESERVOIR_CONDITIONS in compensation_check(reservoir).detail


def test_unit_factors_reproduce_surface_value() -> None:
    rows = intervals(liquid=100.0, oil_mass=45.0, injection=120.0)
    factors = ((1.0, 1.0),) * N_INTERVALS
    reservoir = report_for(rows, 1.19, 1.21, factors)
    assert not [
        item
        for item in reservoir.violations
        if item.kind is ViolationKind.COMPENSATION_OUT_OF_CORRIDOR
    ]


def test_missing_factors_report_surface_conditions_explicitly() -> None:
    rows = intervals(liquid=100.0, oil_mass=45.0, injection=120.0)
    report = report_for(rows, 1.19, 1.21)
    check = compensation_check(report)
    assert COMPENSATION_SURFACE_CONDITIONS in check.detail
    assert COMPENSATION_SURFACE_NOTICE in check.detail
    assert COMPENSATION_RESERVOIR_CONDITIONS not in check.detail


def test_reservoir_factors_without_density_are_an_error() -> None:
    schedule = make_schedule()
    rows = intervals(liquid=100.0, oil_mass=45.0, injection=120.0)
    with pytest.raises(ValueError, match="плотность нефти не передана"):
        validate_dynamic(
            schedule,
            states_for(schedule),
            rows,
            constraints_with(1.19, 1.21),
            oil_density_t_per_m3=None,
            report_undershoot=False,
            reservoir_factors=((1.2, 1.05),) * N_INTERVALS,
        )


def test_short_reservoir_factors_are_an_error() -> None:
    rows = intervals(liquid=100.0, oil_mass=45.0, injection=120.0)
    with pytest.raises(ValueError, match="не передана"):
        report_for(rows, 1.19, 1.21, ((1.2, 1.05),))


def test_zero_withdrawal_stays_compensation_undefined() -> None:
    rows = intervals(liquid=0.0, oil_mass=0.0, injection=120.0)
    report = report_for(rows, 1.19, 1.21)
    undefined = [
        item
        for item in report.violations
        if item.kind is ViolationKind.COMPENSATION_UNDEFINED
    ]
    assert len(undefined) == N_INTERVALS
    assert COMPENSATION_SURFACE_CONDITIONS in undefined[0].detail


def test_zero_withdrawal_stays_undefined_in_reservoir_conditions() -> None:
    rows = intervals(liquid=0.0, oil_mass=0.0, injection=120.0)
    report = report_for(rows, 1.19, 1.21, ((1.2, 1.05),) * N_INTERVALS)
    undefined = [
        item
        for item in report.violations
        if item.kind is ViolationKind.COMPENSATION_UNDEFINED
    ]
    assert len(undefined) == N_INTERVALS
    assert COMPENSATION_RESERVOIR_CONDITIONS in undefined[0].detail


def test_zero_withdrawal_leaves_no_distribution_for_the_tool() -> None:
    rows = intervals(liquid=0.0, oil_mass=0.0, injection=120.0)
    with pytest.raises(CompensationRangeError, match="не определена нигде"):
        compensation_range(rows)


def test_control_step_pressures_follow_the_level_axis() -> None:
    series = tuple(float(index) for index in range(400))
    projected = control_step_pressures(series, 3)
    assert projected == (
        float(FIRST_CONTROL_LEVEL_DECK_DATE_INDEX),
        float(FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + 1),
        float(FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + 2),
    )


def test_control_step_pressures_refuse_a_short_series() -> None:
    with pytest.raises(ValueError, match="короче горизонта"):
        control_step_pressures((1.0, 2.0), 3)
