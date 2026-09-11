from __future__ import annotations

from backend.contexts.schedule.domain.validation.constants import (
    FIRST_CONTROL_DECK_DATE_INDEX,
)

from collections.abc import (
    Sequence,
)
from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.schedule.domain.validate import (
    Violation,
    ViolationKind,
)


def check_response_axes(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    interval_responses: Sequence[IntervalResponse],
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    wells = tuple(schedule.meta.wells)
    n_intervals = schedule.meta.n_intervals
    n_deck_dates = n_intervals + FIRST_CONTROL_DECK_DATE_INDEX + 1

    seen_states = {(state.deck_date_index, state.well) for state in states}
    expected_states = len(wells) * n_deck_dates
    if len(seen_states) != expected_states:
        found.append(
            Violation(
                kind=ViolationKind.RESPONSE_AXIS_INCOMPLETE,
                control_step=None,
                well=None,
                value=float(len(seen_states)),
                detail=(
                    f"StateAtDate: {len(seen_states)} (date, well) pairs "
                    f"against the expected {expected_states} = "
                    f"{len(wells)} x {n_deck_dates}"
                ),
            )
        )

    seen_intervals = {
        (item.control_step, item.well) for item in interval_responses
    }
    expected_intervals = len(wells) * n_intervals
    if len(seen_intervals) != expected_intervals:
        found.append(
            Violation(
                kind=ViolationKind.RESPONSE_AXIS_INCOMPLETE,
                control_step=None,
                well=None,
                value=float(len(seen_intervals)),
                detail=(
                    f"IntervalResponse: {len(seen_intervals)} (step, well) "
                    f"pairs against the expected {expected_intervals} = "
                    f"{len(wells)} x {n_intervals}"
                ),
            )
        )
    return tuple(found)


__all__ = [
    "check_response_axes",
]
