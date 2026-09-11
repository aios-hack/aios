from __future__ import annotations

from collections.abc import Sequence

from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.schedule import ControlEvent, Schedule
from backend.contexts.schedule.domain.validate.deck import (
    check_conflicts,
    check_constraints,
    check_fixed_layer,
)
from backend.contexts.schedule.domain.validate.events import (
    CandidateEvent,
    _well_sort_key,
    candidates,
)
from backend.contexts.schedule.domain.validate.roles import (
    check_roles_and_conversions,
)
from backend.contexts.schedule.domain.validate.setpoints import (
    check_lrat_ceiling,
    check_setpoint_ranges,
    check_step_range,
)
from backend.contexts.schedule.domain.validate.vocabulary import (
    ValidationReport,
    Violation,
)


def validate_static(
    schedule: Schedule,
    constraints: Constraints | None = None,
    expected_fixed_events_hash: str | None = None,
    candidate_events: Sequence[ControlEvent | CandidateEvent] | None = None,
) -> ValidationReport:
    events = (
        candidates(candidate_events)
        if candidate_events is not None
        else candidates(schedule.control_events)
    )
    n_intervals = schedule.meta.n_intervals
    violations: list[Violation] = []
    violations.extend(check_step_range(events, n_intervals))
    violations.extend(check_setpoint_ranges(events))
    violations.extend(check_lrat_ceiling(events))
    violations.extend(
        check_roles_and_conversions(
            events, schedule.initial_state, schedule.fixed_deck_events
        )
    )
    violations.extend(check_conflicts(events))
    violations.extend(
        check_fixed_layer(schedule.fixed_deck_events, expected_fixed_events_hash)
    )
    outage_violations, _outage_check = check_constraints(events, constraints)
    violations.extend(outage_violations)
    violations.sort(
        key=lambda item: (
            -1 if item.control_step is None else item.control_step,
            _well_sort_key(item.well) if item.well is not None else (2, 0, ""),
            item.kind.value,
        )
    )
    return ValidationReport(
        violations=tuple(violations),
        n_control_events=len(events),
        n_fixed_events=len(schedule.fixed_deck_events),
        n_intervals=n_intervals,
    )
