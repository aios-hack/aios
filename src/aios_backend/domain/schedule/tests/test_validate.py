
import pytest

from aios_backend.core.contracts import (
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    MAX_LRAT_M3_PER_DAY,
    N_INTERVALS,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellOutage,
    WellState,
)
from aios_backend.domain.schedule import load_schedule
from aios_backend.domain.schedule.validate import (
    CandidateEvent,
    StaticValidationError,
    ValidationReport,
    ViolationKind,
    check_lrat_ceiling,
    fixed_layer_hash,
    validate_static,
)

from conftest import missing_reason, model_z_schedule

MODEL_Z_SCHEDULE = model_z_schedule()

pytestmark = pytest.mark.skipif(
    MODEL_Z_SCHEDULE is None,
    reason=missing_reason("дек Model_Z"),
)


@pytest.fixture(scope="module")
def deck_schedule() -> Schedule:
    return load_schedule(MODEL_Z_SCHEDULE)


def make_schedule(
    initial_state: dict[str, WellState],
    control_events: tuple[ControlEvent, ...] = (),
    fixed_deck_events: tuple[FixedDeckEvent, ...] = (),
    n_intervals: int = N_INTERVALS,
) -> Schedule:
    wells = tuple(sorted(initial_state))
    return Schedule(
        meta=ScheduleMeta(wells=wells, n_intervals=n_intervals),
        initial_state=initial_state,
        fixed_deck_events=fixed_deck_events,
        control_events=control_events,
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


def test_real_deck_has_no_static_violations(deck_schedule: Schedule) -> None:
    report = validate_static(deck_schedule)
    assert report.ok, report.format()
    assert report.violations == ()
    assert report.n_intervals == N_INTERVALS
    assert report.n_control_events > 0
    report.raise_if_violated()


def test_real_deck_stays_below_lrat_ceiling(deck_schedule: Schedule) -> None:
    setpoints = [
        event.value
        for event in deck_schedule.control_events
        if event.kind is EventKind.SET_LRAT and event.value is not None
    ]
    assert max(setpoints) <= MAX_LRAT_M3_PER_DAY
    assert check_lrat_ceiling(
        tuple(
            CandidateEvent(
                control_step=event.control_step,
                well=event.well,
                kind=event.kind,
                value=event.value,
            )
            for event in deck_schedule.control_events
        )
    ) == ()


def test_lrat_ceiling_reports_501() -> None:
    schedule = make_schedule({"W1": producer()})
    over = CandidateEvent(
        control_step=3, well="W1", kind=EventKind.SET_LRAT, value=501.0
    )
    report = validate_static(schedule, candidate_events=(over,))
    assert not report.ok
    assert report.counts() == {ViolationKind.LRAT_ABOVE_CEILING: 1}
    violation = report.violations[0]
    assert violation.control_step == 3
    assert violation.well == "W1"
    assert violation.value == 501.0


def test_lrat_exactly_at_ceiling_passes() -> None:
    schedule = make_schedule({"W1": producer()})
    at_ceiling = CandidateEvent(
        control_step=0, well="W1", kind=EventKind.SET_LRAT, value=MAX_LRAT_M3_PER_DAY
    )
    assert validate_static(schedule, candidate_events=(at_ceiling,)).ok


def test_control_event_constructor_also_rejects_ceiling() -> None:
    with pytest.raises(ValueError):
        ControlEvent(
            control_step=0,
            well="W1",
            kind=EventKind.SET_LRAT,
            value=MAX_LRAT_M3_PER_DAY + 0.1,
        )


def test_negative_setpoint_reported_for_both_kinds() -> None:
    schedule = make_schedule({"P1": producer(), "I1": injector()})
    events = (
        CandidateEvent(control_step=1, well="P1", kind=EventKind.SET_LRAT, value=-1.0),
        CandidateEvent(control_step=1, well="I1", kind=EventKind.SET_RATE, value=-5.0),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.NEGATIVE_SETPOINT: 2}


def test_event_addressed_to_not_commissioned_well() -> None:
    schedule = make_schedule({"W1": not_commissioned()})
    events = (
        CandidateEvent(control_step=5, well="W1", kind=EventKind.SET_LRAT, value=30.0),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.WELL_NOT_COMMISSIONED: 1}


def test_commissioning_inside_horizon_lifts_not_commissioned() -> None:
    schedule = make_schedule(
        {"W1": not_commissioned()},
        fixed_deck_events=(
            FixedDeckEvent(
                control_step=10, well="W1", operator="WCONPROD", raw_args=("OPEN",)
            ),
        ),
    )
    before = validate_static(
        schedule,
        candidate_events=(
            CandidateEvent(
                control_step=9, well="W1", kind=EventKind.SET_LRAT, value=30.0
            ),
        ),
    )
    after = validate_static(
        schedule,
        candidate_events=(
            CandidateEvent(
                control_step=11, well="W1", kind=EventKind.SET_LRAT, value=30.0
            ),
        ),
    )
    assert before.counts() == {ViolationKind.WELL_NOT_COMMISSIONED: 1}
    assert after.ok


def test_set_lrat_on_injector_is_reported() -> None:
    schedule = make_schedule({"I1": injector()})
    events = (
        CandidateEvent(control_step=2, well="I1", kind=EventKind.SET_LRAT, value=40.0),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.SET_LRAT_ON_INJECTOR: 1}


def test_set_rate_on_producer_is_reported() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(control_step=2, well="P1", kind=EventKind.SET_RATE, value=40.0),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.SET_RATE_ON_PRODUCER: 1}


def test_conversion_step_zero_lrat_is_the_closing_producer_record() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(control_step=4, well="P1", kind=EventKind.CONVERT_INJ),
        CandidateEvent(control_step=4, well="P1", kind=EventKind.SET_LRAT, value=0.0),
        CandidateEvent(control_step=4, well="P1", kind=EventKind.SET_RATE, value=90.0),
        CandidateEvent(control_step=5, well="P1", kind=EventKind.SET_RATE, value=90.0),
    )
    assert validate_static(schedule, candidate_events=events).ok

    after_conversion = events + (
        CandidateEvent(control_step=6, well="P1", kind=EventKind.SET_LRAT, value=10.0),
    )
    report = validate_static(schedule, candidate_events=after_conversion)
    assert report.counts() == {ViolationKind.SET_LRAT_ON_INJECTOR: 1}


def test_repeated_convert_inj_is_reported() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(control_step=4, well="P1", kind=EventKind.CONVERT_INJ),
        CandidateEvent(control_step=9, well="P1", kind=EventKind.CONVERT_INJ),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.CONVERT_INJ_REPEATED: 1}
    assert report.violations[0].control_step == 9


def test_convert_inj_on_injector_is_reported() -> None:
    schedule = make_schedule({"I1": injector()})
    events = (CandidateEvent(control_step=3, well="I1", kind=EventKind.CONVERT_INJ),)
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.CONVERT_INJ_ON_INJECTOR: 1}


def test_terminal_step_carries_no_control_event() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(
            control_step=N_INTERVALS, well="P1", kind=EventKind.SET_LRAT, value=30.0
        ),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.TERMINAL_STEP_HAS_CONTROL: 1}
    assert report.violations[0].control_step == N_INTERVALS


def test_step_out_of_range_is_reported() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(control_step=-1, well="P1", kind=EventKind.SET_LRAT, value=30.0),
        CandidateEvent(control_step=900, well="P1", kind=EventKind.SET_LRAT, value=30.0),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.STEP_OUT_OF_RANGE: 2}


def test_conflicting_events_on_one_step() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(control_step=7, well="P1", kind=EventKind.SET_LRAT, value=30.0),
        CandidateEvent(control_step=7, well="P1", kind=EventKind.SET_LRAT, value=40.0),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.CONFLICTING_EVENTS: 1}


def test_exact_duplicates_are_not_conflicts() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(control_step=7, well="P1", kind=EventKind.SET_LRAT, value=30.0),
        CandidateEvent(control_step=7, well="P1", kind=EventKind.SET_LRAT, value=30.0),
    )
    assert validate_static(schedule, candidate_events=events).ok


def test_fixed_layer_change_is_reported(deck_schedule: Schedule) -> None:
    expected = fixed_layer_hash(deck_schedule.fixed_deck_events)
    assert validate_static(
        deck_schedule, expected_fixed_events_hash=expected
    ).ok
    tampered = Schedule(
        meta=deck_schedule.meta,
        initial_state=deck_schedule.initial_state,
        fixed_deck_events=tuple(deck_schedule.fixed_deck_events)[:-1],
        control_events=deck_schedule.control_events,
    )
    report = validate_static(tampered, expected_fixed_events_hash=expected)
    assert report.counts() == {ViolationKind.FIXED_LAYER_CHANGED: 1}


def test_constraints_outage_window_is_checked() -> None:
    schedule = make_schedule({"P1": producer()})
    constraints = Constraints(
        well_outages=(WellOutage(well="P1", control_step_from=5, control_step_to=8),)
    )
    events = (
        CandidateEvent(control_step=6, well="P1", kind=EventKind.SET_LRAT, value=30.0),
        CandidateEvent(control_step=9, well="P1", kind=EventKind.SET_LRAT, value=30.0),
    )
    report = validate_static(schedule, constraints=constraints, candidate_events=events)
    assert report.counts() == {ViolationKind.WELL_OUTAGE_VIOLATED: 1}
    assert report.violations[0].control_step == 6


def test_report_lists_every_problem_at_once() -> None:
    schedule = make_schedule({"P1": producer(), "I1": injector()})
    events = (
        CandidateEvent(control_step=1, well="P1", kind=EventKind.SET_LRAT, value=900.0),
        CandidateEvent(control_step=2, well="P1", kind=EventKind.SET_LRAT, value=-3.0),
        CandidateEvent(control_step=3, well="I1", kind=EventKind.SET_LRAT, value=10.0),
        CandidateEvent(
            control_step=N_INTERVALS, well="P1", kind=EventKind.SHUT
        ),
    )
    report = validate_static(schedule, candidate_events=events)
    assert len(report.violations) == 4
    assert set(report.counts()) == {
        ViolationKind.LRAT_ABOVE_CEILING,
        ViolationKind.NEGATIVE_SETPOINT,
        ViolationKind.SET_LRAT_ON_INJECTOR,
        ViolationKind.TERMINAL_STEP_HAS_CONTROL,
    }
    assert report.violations == tuple(
        sorted(report.violations, key=lambda item: item.control_step)
    )
    with pytest.raises(StaticValidationError) as error:
        report.raise_if_violated()
    assert error.value.report is report
    assert "LRAT_ABOVE_CEILING" in str(error.value)


def test_missing_and_unexpected_values_are_reported() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(control_step=1, well="P1", kind=EventKind.SET_LRAT, value=None),
        CandidateEvent(control_step=2, well="P1", kind=EventKind.SHUT, value=7.0),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {
        ViolationKind.MISSING_VALUE: 1,
        ViolationKind.UNEXPECTED_VALUE: 1,
    }


def test_event_addressed_to_well_outside_axis() -> None:
    schedule = make_schedule({"P1": producer()})
    events = (
        CandidateEvent(control_step=1, well="ZZ", kind=EventKind.SET_LRAT, value=30.0),
    )
    report = validate_static(schedule, candidate_events=events)
    assert report.counts() == {ViolationKind.WELL_NOT_ON_AXIS: 1}


def test_report_is_a_structure_not_a_boolean() -> None:
    schedule = make_schedule({"P1": producer()})
    report = validate_static(schedule)
    assert isinstance(report, ValidationReport)
    assert report.ok
    assert "нарушений нет" in report.format()
