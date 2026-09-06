from datetime import date
from dataclasses import replace
from backend.core.contracts import Constraints, ControlEvent, EventKind, WellOutage
from backend.domain.schedule.case_limits import apply_case_limits
from tests.application.test_run_workflow import sample_schedule


def dense_schedule():
    return replace(sample_schedule(), control_events=tuple(
        event for step in range(3) for event in (
            ControlEvent(step, 'W1', EventKind.SET_LRAT, 10),
            ControlEvent(step, 'W1', EventKind.OPEN))))


def test_outage_includes_both_endpoints_without_changing_history():
    base = dense_schedule()
    changed = apply_case_limits(base, Constraints(well_outages=(WellOutage('W1', 0, 1),)), [date(2007, 1, 1)] * 3)
    assert changed.initial_state == base.initial_state
    assert changed.fixed_deck_events == base.fixed_deck_events
    for event in changed.control_events:
        if event.control_step <= 1:
            assert event.kind is not EventKind.OPEN
            if event.value is not None: assert event.value == 0
        elif event.kind is EventKind.SET_LRAT: assert event.value == 10


def test_liquid_cap_only_applies_to_requested_year():
    changed = apply_case_limits(dense_schedule(), Constraints(liquid_limits={2007: 3}),
                                [date(2007, 1, 1), date(2008, 1, 1), date(2009, 1, 1)])
    rates = [e.value for e in changed.control_events if e.kind is EventKind.SET_LRAT]
    assert rates == [3, 10, 10]
