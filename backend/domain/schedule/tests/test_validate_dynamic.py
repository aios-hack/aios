from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from backend.core.contracts import (
    ActiveControlMode,
    Availability,
    Constraints,
    ControlEvent,
    FixedDeckEvent,
    IntervalResponse,
    OperatingStatus,
    Role,
    RunResult,
    RunStatus,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    WellOutage,
    WellState,
)
from backend.domain.schedule import load_schedule
from backend.domain.schedule.validate import ViolationKind

from conftest import base_run_dir, base_run_output_dir, missing_reason
from backend.domain.schedule.validate_dynamic import (
    ACHIEVEMENT_THRESHOLD,
    DYNAMIC_VIOLATION_KINDS,
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
    DynamicValidationError,
    FIRST_CONTROL_DECK_DATE_INDEX,
    INJECTOR_MAX_BHP_BAR,
    PRODUCER_MIN_BHP_BAR,
    check_interval_signs,
    check_response_axes,
    validate_dynamic,
)


def producer(setpoint: float = 50.0) -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.OPEN,
        setpoint=setpoint,
    )


def injector(setpoint: float = 80.0) -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.INJ,
        operating_status=OperatingStatus.OPEN,
        setpoint=setpoint,
    )


def not_commissioned() -> WellState:
    return WellState(
        availability=Availability.NOT_COMMISSIONED,
        role=Role.NONE,
        operating_status=OperatingStatus.SHUT,
        setpoint=0.0,
    )


def make_schedule(
    initial_state: dict[str, WellState],
    control_events: tuple[ControlEvent, ...] = (),
    fixed_deck_events: tuple[FixedDeckEvent, ...] = (),
    n_intervals: int = 3,
) -> Schedule:
    wells = tuple(sorted(initial_state))
    return Schedule(
        meta=ScheduleMeta(wells=wells, n_intervals=n_intervals),
        initial_state=initial_state,
        fixed_deck_events=fixed_deck_events,
        control_events=control_events,
    )


def state(
    control_step: int,
    well: str,
    *,
    liquid_rate: float = 0.0,
    oil_rate: float = 0.0,
    injection_rate: float = 0.0,
    bhp: float = 120.0,
    mode: ActiveControlMode = ActiveControlMode.RATE_TARGET,
) -> StateAtDate:
    return StateAtDate(
        deck_date_index=FIRST_CONTROL_DECK_DATE_INDEX + 1 + control_step,
        well=well,
        liquid_rate=liquid_rate,
        oil_rate=oil_rate,
        injection_rate=injection_rate,
        thp=20.0,
        bhp=bhp,
        well_efficiency=1.0,
        active_control_mode=mode,
    )


def interval(
    control_step: int,
    well: str,
    *,
    oil: float = 0.0,
    liquid: float = 0.0,
    injection: float = 0.0,
) -> IntervalResponse:
    return IntervalResponse(
        control_step=control_step,
        well=well,
        oil_mass_delta=oil,
        liquid_volume_delta=liquid,
        injection_volume_delta=injection,
    )


def full_states(schedule: Schedule, **kwargs: float) -> tuple[StateAtDate, ...]:
    result: list[StateAtDate] = []
    for well in schedule.meta.wells:
        for index in range(
            schedule.meta.n_intervals + FIRST_CONTROL_DECK_DATE_INDEX + 1
        ):
            control_step = index - FIRST_CONTROL_DECK_DATE_INDEX - 1
            result.append(
                StateAtDate(
                    deck_date_index=index,
                    well=well,
                    liquid_rate=kwargs.get("liquid_rate", 0.0),
                    oil_rate=0.0,
                    injection_rate=kwargs.get("injection_rate", 0.0),
                    thp=20.0,
                    bhp=kwargs.get("bhp", 120.0),
                    well_efficiency=1.0,
                    active_control_mode=(
                        ActiveControlMode.RATE_TARGET
                        if control_step >= 0
                        else ActiveControlMode.RATE_TARGET
                    ),
                )
            )
    return tuple(result)


def full_intervals(schedule: Schedule) -> tuple[IntervalResponse, ...]:
    return tuple(
        interval(step, well)
        for well in schedule.meta.wells
        for step in range(schedule.meta.n_intervals)
    )


def test_dynamic_kinds_live_in_the_static_enum() -> None:
    assert DYNAMIC_VIOLATION_KINDS
    for kind in DYNAMIC_VIOLATION_KINDS:
        assert isinstance(kind, ViolationKind)
        assert getattr(ViolationKind, kind.name) is kind


def test_blocking_kinds_are_a_physical_subset_of_all_diagnostics() -> None:
    assert BLOCKING_DYNAMIC_VIOLATION_KINDS < DYNAMIC_VIOLATION_KINDS
    assert ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED in BLOCKING_DYNAMIC_VIOLATION_KINDS
    assert ViolationKind.OPEN_WITHOUT_FLOW not in BLOCKING_DYNAMIC_VIOLATION_KINDS
    assert ViolationKind.NEGATIVE_INTERVAL_DELTA not in BLOCKING_DYNAMIC_VIOLATION_KINDS


def test_target_ratio_only_for_active_wells_with_positive_setpoint() -> None:
    schedule = make_schedule(
        {"P1": producer(50.0), "S1": producer(0.0), "N1": not_commissioned()},
        n_intervals=1,
    )
    states = (
        state(0, "P1", liquid_rate=50.0),
        state(0, "S1", mode=ActiveControlMode.SHUT),
        state(0, "N1", mode=ActiveControlMode.NOT_COMMISSIONED),
    )
    report = validate_dynamic(schedule, states, ())
    assert [item.well for item in report.ratios] == ["P1"]


def test_undershoot_is_reported_with_ratio() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (
        state(0, "P1", liquid_rate=20.0, mode=ActiveControlMode.BHP_LIMITED, bhp=50.0),
    )
    report = validate_dynamic(schedule, states, ())
    assert report.counts()[ViolationKind.TARGET_UNDERSHOOT] == 1
    ratio = report.ratios[0]
    assert ratio.target == 50.0
    assert ratio.actual == 20.0
    assert ratio.ratio == pytest.approx(0.4)
    assert not ratio.achieved
    assert report.undershooting() == (ratio,)


def test_exactly_at_threshold_is_achieved() -> None:
    schedule = make_schedule({"P1": producer(100.0)}, n_intervals=1)
    states = (state(0, "P1", liquid_rate=100.0 * ACHIEVEMENT_THRESHOLD),)
    report = validate_dynamic(schedule, states, ())
    assert report.ratios[0].achieved
    assert ViolationKind.TARGET_UNDERSHOOT not in report.counts()


def test_undershoot_can_be_downgraded_to_diagnostics() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (
        state(0, "P1", liquid_rate=10.0, mode=ActiveControlMode.BHP_LIMITED, bhp=50.0),
    )
    loud = validate_dynamic(schedule, states, ())
    quiet = validate_dynamic(schedule, states, (), report_undershoot=False)
    assert loud.counts()[ViolationKind.TARGET_UNDERSHOOT] == 1
    assert ViolationKind.TARGET_UNDERSHOOT not in quiet.counts()
    assert len(quiet.undershooting()) == 1


def test_bhp_alone_is_not_enough_undershoot_carries_the_signal() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (
        state(
            0,
            "P1",
            liquid_rate=12.0,
            bhp=PRODUCER_MIN_BHP_BAR,
            mode=ActiveControlMode.BHP_LIMITED,
        ),
    )
    report = validate_dynamic(schedule, states, ())
    counts = report.counts()
    assert ViolationKind.BHP_BELOW_PRODUCER_LIMIT not in counts
    assert counts[ViolationKind.TARGET_UNDERSHOOT] == 1


def test_producer_below_50_bar_is_reported() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (state(0, "P1", liquid_rate=50.0, bhp=PRODUCER_MIN_BHP_BAR - 1),)
    report = validate_dynamic(schedule, states, ())
    assert report.counts()[ViolationKind.BHP_BELOW_PRODUCER_LIMIT] == 1


def test_injector_above_300_bar_is_reported() -> None:
    schedule = make_schedule({"I1": injector(80.0)}, n_intervals=1)
    states = (
        state(0, "I1", injection_rate=80.0, bhp=INJECTOR_MAX_BHP_BAR + 1),
    )
    report = validate_dynamic(schedule, states, ())
    assert report.counts()[ViolationKind.BHP_ABOVE_INJECTOR_LIMIT] == 1


def test_bhp_exactly_at_limits_passes() -> None:
    schedule = make_schedule(
        {"P1": producer(50.0), "I1": injector(80.0)}, n_intervals=1
    )
    states = (
        state(0, "P1", liquid_rate=50.0, bhp=PRODUCER_MIN_BHP_BAR),
        state(0, "I1", injection_rate=80.0, bhp=INJECTOR_MAX_BHP_BAR),
    )
    report = validate_dynamic(schedule, states, ())
    counts = report.counts()
    assert ViolationKind.BHP_BELOW_PRODUCER_LIMIT not in counts
    assert ViolationKind.BHP_ABOVE_INJECTOR_LIMIT not in counts


def test_unknown_mode_is_reported() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (
        state(0, "P1", liquid_rate=50.0, mode=ActiveControlMode.UNKNOWN),
    )
    report = validate_dynamic(schedule, states, ())
    assert report.counts()[ViolationKind.MODE_NOT_REPORTED] == 1


def test_mode_contradicting_schedule_is_reported_both_ways() -> None:
    schedule = make_schedule(
        {"P1": producer(50.0), "N1": not_commissioned()}, n_intervals=1
    )
    states = (
        state(0, "P1", liquid_rate=50.0, mode=ActiveControlMode.NOT_COMMISSIONED),
        state(0, "N1", mode=ActiveControlMode.RATE_TARGET),
    )
    report = validate_dynamic(schedule, states, ())
    assert report.counts()[ViolationKind.MODE_CONTRADICTS_SCHEDULE] == 2


def test_bhp_limited_while_target_met_is_contradiction() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (
        state(0, "P1", liquid_rate=50.0, mode=ActiveControlMode.BHP_LIMITED),
    )
    report = validate_dynamic(schedule, states, ())
    assert report.counts()[ViolationKind.BHP_LIMITED_WITHOUT_UNDERSHOOT] == 1


def test_all_five_modes_are_accepted_by_the_validator() -> None:
    seen = set()
    for mode in ActiveControlMode:
        schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
        states = (state(0, "P1", liquid_rate=50.0, mode=mode),)
        validate_dynamic(schedule, states, ())
        seen.add(mode)
    assert seen == set(ActiveControlMode)
    assert len(seen) == 5


def test_injector_producing_and_producer_injecting_are_reported() -> None:
    schedule = make_schedule(
        {"P1": producer(50.0), "I1": injector(80.0)}, n_intervals=1
    )
    states = (
        state(0, "P1", liquid_rate=50.0, injection_rate=3.0),
        state(0, "I1", injection_rate=80.0, liquid_rate=4.0),
    )
    report = validate_dynamic(schedule, states, ())
    assert report.counts()[ViolationKind.ROLE_FACT_MISMATCH] == 2


def test_open_without_flow_and_shut_with_flow() -> None:
    schedule = make_schedule(
        {"P1": producer(50.0), "P2": producer(0.0)}, n_intervals=1
    )
    states = (
        state(0, "P1", liquid_rate=0.0, mode=ActiveControlMode.SHUT),
        state(0, "P2", liquid_rate=7.0, mode=ActiveControlMode.RATE_TARGET),
    )
    report = validate_dynamic(schedule, states, ())
    counts = report.counts()
    assert counts[ViolationKind.OPEN_WITHOUT_FLOW] == 1
    assert counts[ViolationKind.SHUT_WITH_FLOW] == 1


def test_freshly_commissioned_well_is_not_read_as_intentionally_shut() -> None:
    schedule = make_schedule(
        {"N1": not_commissioned()},
        fixed_deck_events=(
            FixedDeckEvent(
                control_step=0, well="N1", operator="WCONINJE", raw_args=("OPEN",)
            ),
        ),
        n_intervals=1,
    )
    states = (
        state(0, "N1", injection_rate=30.0, mode=ActiveControlMode.RATE_TARGET),
    )
    report = validate_dynamic(schedule, states, ())
    counts = report.counts()
    assert ViolationKind.SHUT_WITH_FLOW not in counts
    assert ViolationKind.ROLE_FACT_MISMATCH not in counts


def test_negative_interval_delta_is_reported() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    responses = (interval(0, "P1", liquid=-1.0),)
    assert len(check_interval_signs(responses)) == 1
    report = validate_dynamic(schedule, (state(0, "P1", liquid_rate=50.0),), responses)
    assert report.counts()[ViolationKind.NEGATIVE_INTERVAL_DELTA] == 1


def test_incomplete_axes_are_reported() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=3)
    found = check_response_axes(schedule, (state(0, "P1"),), (interval(0, "P1"),))
    assert len(found) == 2
    assert {item.kind for item in found} == {ViolationKind.RESPONSE_AXIS_INCOMPLETE}


def test_complete_axes_pass() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=3)
    assert (
        check_response_axes(
            schedule, full_states(schedule, liquid_rate=50.0), full_intervals(schedule)
        )
        == ()
    )


def test_constraints_limits_floors_and_outages() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (state(0, "P1", liquid_rate=50.0, oil_rate=1.0),)
    year = schedule.meta.t0.year
    constraints = Constraints(
        liquid_limits={year: 10.0},
        production_floors={year: 5.0},
        well_outages=(WellOutage(well="P1", control_step_from=0, control_step_to=0),),
    )
    report = validate_dynamic(schedule, states, (), constraints)
    counts = report.counts()
    assert counts[ViolationKind.LIQUID_LIMIT_EXCEEDED] == 1
    assert counts[ViolationKind.PRODUCTION_FLOOR_MISSED] == 1
    assert counts[ViolationKind.OUTAGE_WELL_PRODUCED] == 1


def test_injection_limit_is_reported() -> None:
    schedule = make_schedule({"I1": injector(80.0)}, n_intervals=1)
    states = (state(0, "I1", injection_rate=80.0),)
    constraints = Constraints(injection_limits={schedule.meta.t0.year: 10.0})
    report = validate_dynamic(schedule, states, (), constraints)
    assert report.counts()[ViolationKind.INJECTION_LIMIT_EXCEEDED] == 1


def test_watercut_limit_needs_density_and_is_reported() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (state(0, "P1", liquid_rate=50.0),)
    responses = (interval(0, "P1", oil=1.0, liquid=1000.0),)
    constraints = Constraints(watercut_limits={schedule.meta.t0.year: 0.5})
    with pytest.raises(ValueError):
        validate_dynamic(schedule, states, responses, constraints)
    report = validate_dynamic(
        schedule, states, responses, constraints, oil_density_t_per_m3=0.9
    )
    assert report.counts()[ViolationKind.WATERCUT_LIMIT_EXCEEDED] == 1


def test_injection_cannot_exceed_produced_water_without_external_source() -> None:
    schedule = make_schedule(
        {"P1": producer(50.0), "I1": injector(80.0)}, n_intervals=1
    )
    states = (
        state(0, "P1", liquid_rate=50.0),
        state(0, "I1", injection_rate=80.0),
    )
    responses = (
        interval(0, "P1", oil=45.0, liquid=100.0),
        interval(0, "I1", injection=60.0),
    )
    constraints = Constraints(
        infrastructure={"water_reinjection_fraction": 1.0}
    )

    report = validate_dynamic(
        schedule, states, responses, constraints, oil_density_t_per_m3=0.9
    )

    assert report.counts()[ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED] == 1


def test_external_water_and_lag_are_accounted_in_volume_balance() -> None:
    schedule = make_schedule(
        {"P1": producer(50.0), "I1": injector(80.0)}, n_intervals=2
    )
    states = (
        state(0, "P1", liquid_rate=50.0),
        state(0, "I1", injection_rate=80.0),
        state(1, "P1", liquid_rate=50.0),
        state(1, "I1", injection_rate=80.0),
    )
    responses = (
        interval(0, "P1", oil=0.0, liquid=100.0),
        interval(0, "I1", injection=31.0),
        interval(1, "P1", oil=0.0, liquid=100.0),
        interval(1, "I1", injection=128.0),
    )
    constraints = Constraints(
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "water_reinjection_lag_steps": 1,
            "external_water_m3_per_day": 1.0,
        }
    )

    report = validate_dynamic(
        schedule, states, responses, constraints, oil_density_t_per_m3=0.9
    )

    assert ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED not in report.counts()


def test_clean_response_has_no_violations_and_raises_nothing() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=3)
    states = full_states(schedule, liquid_rate=50.0)
    report = validate_dynamic(schedule, states, full_intervals(schedule))
    assert report.ok, report.format()
    assert report.violations == ()
    assert "нарушений нет" in report.format()
    report.raise_if_violated()


def test_raise_if_violated_carries_the_report() -> None:
    schedule = make_schedule({"P1": producer(50.0)}, n_intervals=1)
    states = (state(0, "P1", liquid_rate=1.0, mode=ActiveControlMode.BHP_LIMITED),)
    report = validate_dynamic(schedule, states, ())
    with pytest.raises(DynamicValidationError) as excinfo:
        report.raise_if_violated()
    assert excinfo.value.report is report


def test_violations_are_sorted_and_addressable() -> None:
    schedule = make_schedule(
        {"P1": producer(50.0), "P2": producer(50.0)}, n_intervals=3
    )
    states = (
        state(2, "P2", liquid_rate=1.0),
        state(0, "P1", liquid_rate=1.0),
        state(1, "P1", liquid_rate=1.0),
    )
    report = validate_dynamic(schedule, states, ())
    addressed = [item for item in report.violations if item.control_step is not None]
    assert addressed
    steps = [item.control_step for item in addressed]
    assert steps == sorted(steps)
    for item in addressed:
        assert item.well is not None
        assert str(item).startswith("[")
    assert report.violations[0].control_step is None


def _load_real_response():
    output = base_run_output_dir()
    if output is None:
        return None
    deck = base_run_dir() / "deck"
    if not (deck / "Model_Z_sch.inc").is_file():
        return None
    from backend.infrastructure.opm import ResponseLoader, build_summary_plan, load_density_by_pvtnum

    schedule = load_schedule(deck / "Model_Z_sch.inc")
    plan = build_summary_plan(deck, sorted(schedule.meta.wells))
    density = load_density_by_pvtnum(deck)
    run_result = RunResult(
        run_id=output.parent.name,
        status=RunStatus.OK,
        deck_hash="",
        canonical_schedule_hash="",
        summary_hash="",
        artifacts=tuple(str(path) for path in output.iterdir()),
        wallclock_seconds=0.0,
        message="",
    )
    artifact = ResponseLoader().load(run_result, plan, schedule, density)
    return schedule, artifact


REAL_RESPONSE = _load_real_response()

real_response = pytest.mark.skipif(
    REAL_RESPONSE is None,
    reason=missing_reason("сохранённый отклик настоящего прогона OPM"),
)


@real_response
def test_real_response_axes_are_complete() -> None:
    schedule, artifact = REAL_RESPONSE
    report = validate_dynamic(
        schedule, artifact.state_at_date, artifact.interval_response
    )
    assert report.n_wells == len(schedule.meta.wells)
    assert report.n_intervals_seen == schedule.meta.n_intervals
    assert ViolationKind.RESPONSE_AXIS_INCOMPLETE not in report.counts()


@real_response
def test_real_response_has_no_negative_deltas_and_no_unknown_modes() -> None:
    schedule, artifact = REAL_RESPONSE
    report = validate_dynamic(
        schedule, artifact.state_at_date, artifact.interval_response
    )
    counts = report.counts()
    assert ViolationKind.NEGATIVE_INTERVAL_DELTA not in counts
    assert ViolationKind.MODE_NOT_REPORTED not in counts
    assert ViolationKind.MODE_CONTRADICTS_SCHEDULE not in counts
    assert ViolationKind.ROLE_FACT_MISMATCH not in counts


@real_response
def test_real_response_undershoot_is_explained_by_mode() -> None:
    schedule, artifact = REAL_RESPONSE
    report = validate_dynamic(
        schedule, artifact.state_at_date, artifact.interval_response
    )
    undershooting = report.undershooting()
    assert undershooting
    assert all(
        item.mode in (ActiveControlMode.BHP_LIMITED, ActiveControlMode.SHUT)
        for item in undershooting
    )
    assert any(item.mode is ActiveControlMode.BHP_LIMITED for item in undershooting)


@real_response
def test_real_response_bhp_limited_is_the_dominant_undershoot_cause() -> None:
    schedule, artifact = REAL_RESPONSE
    report = validate_dynamic(
        schedule, artifact.state_at_date, artifact.interval_response
    )
    modes = report.modes()
    assert modes[ActiveControlMode.BHP_LIMITED] > 0
    assert modes[ActiveControlMode.RATE_TARGET] > 0
    assert set(modes) <= set(ActiveControlMode)


@real_response
def test_real_response_open_without_flow_stops_at_first_perforation() -> None:
    schedule, artifact = REAL_RESPONSE
    report = validate_dynamic(
        schedule, artifact.state_at_date, artifact.interval_response
    )
    stranded = [
        item
        for item in report.violations
        if item.kind is ViolationKind.OPEN_WITHOUT_FLOW
    ]
    assert stranded
    by_well: dict[str, list[int]] = {}
    for item in stranded:
        by_well.setdefault(item.well, []).append(item.control_step)
    perforations = {
        event.well: event.control_step
        for event in sorted(
            schedule.fixed_deck_events, key=lambda item: -item.control_step
        )
        if event.operator == "COMPDAT"
    }
    for well, steps in by_well.items():
        first_perforation = perforations.get(well)
        assert first_perforation is not None
        assert max(steps) < first_perforation
