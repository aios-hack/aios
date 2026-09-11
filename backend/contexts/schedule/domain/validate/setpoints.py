from __future__ import annotations

from collections.abc import Sequence

from backend.contexts.schedule.domain.schedule import (
    EventKind,
    MAX_LRAT_M3_PER_DAY,
    N_INTERVALS,
)
from backend.contexts.schedule.domain.validate.events import (
    CandidateEvent,
    _event_sort_key,
)
from backend.contexts.schedule.domain.validate.vocabulary import (
    MIN_SETPOINT_M3_PER_DAY,
    Violation,
    ViolationKind,
)


def check_lrat_ceiling(
    events: Sequence[CandidateEvent],
    ceiling: float = MAX_LRAT_M3_PER_DAY,
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for event in sorted(events, key=_event_sort_key):
        if event.kind is not EventKind.SET_LRAT or event.value is None:
            continue
        if event.value > ceiling:
            found.append(
                Violation(
                    kind=ViolationKind.LRAT_ABOVE_CEILING,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=(
                        f"the LRAT setpoint exceeds the Methodology ceiling "
                        f"{ceiling} m3/day by {event.value - ceiling} m3/day; "
                        f"the reference calculator fails with an error on "
                        f"such input"
                    ),
                )
            )
    return tuple(found)


def check_setpoint_ranges(
    events: Sequence[CandidateEvent],
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for event in sorted(events, key=_event_sort_key):
        needs_value = event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE)
        if needs_value and event.value is None:
            found.append(
                Violation(
                    kind=ViolationKind.MISSING_VALUE,
                    control_step=event.control_step,
                    well=event.well,
                    value=None,
                    detail=(
                        f"{event.kind.name} requires a setpoint, the value is "
                        f"missing"
                    ),
                )
            )
            continue
        if not needs_value and event.value is not None:
            found.append(
                Violation(
                    kind=ViolationKind.UNEXPECTED_VALUE,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=f"{event.kind.name} does not accept a setpoint",
                )
            )
            continue
        if event.value is not None and event.value < MIN_SETPOINT_M3_PER_DAY:
            found.append(
                Violation(
                    kind=ViolationKind.NEGATIVE_SETPOINT,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name}: negative setpoint, allowed from "
                        f"{MIN_SETPOINT_M3_PER_DAY} m3/day"
                    ),
                )
            )
    return tuple(found)


def check_step_range(
    events: Sequence[CandidateEvent], n_intervals: int = N_INTERVALS
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for event in sorted(events, key=_event_sort_key):
        if event.control_step == n_intervals:
            found.append(
                Violation(
                    kind=ViolationKind.TERMINAL_STEP_HAS_CONTROL,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name} is assigned to the terminal step "
                        f"{n_intervals}: it has no interval and carries no "
                        f"decisions"
                    ),
                )
            )
        elif not (0 <= event.control_step < n_intervals):
            found.append(
                Violation(
                    kind=ViolationKind.STEP_OUT_OF_RANGE,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name}: step outside the range "
                        f"0...{n_intervals - 1}"
                    ),
                )
            )
    return tuple(found)
