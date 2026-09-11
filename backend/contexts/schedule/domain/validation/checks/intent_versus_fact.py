from __future__ import annotations

from backend.contexts.schedule.domain.validation.interpreter import (
    _states_by_step,
    _target_at,
    _target_timeline,
)
from collections.abc import (
    Sequence,
)
from backend.contexts.schedule.domain.schedule import OperatingStatus, Schedule
from backend.contexts.reservoir.domain.response import StateAtDate
from backend.contexts.schedule.domain.validate import (
    Violation,
    ViolationKind,
    _well_sort_key,
)


def check_intent_versus_fact(
    schedule: Schedule,
    states: Sequence[StateAtDate],
) -> tuple[Violation, ...]:
    timelines = _target_timeline(schedule)
    indexed = _states_by_step(states)
    found: list[Violation] = []
    for (control_step, well), state in sorted(
        indexed.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        timeline = timelines.get(well)
        if timeline is None:
            continue
        target = _target_at(timeline, control_step)
        if not target.commissioned:
            continue
        if not target.setpoint_known:
            continue
        flowing = state.liquid_rate > 0.0 or state.injection_rate > 0.0
        wants_open = (
            target.operating_status is OperatingStatus.OPEN and target.setpoint > 0.0
        )
        if wants_open and not flowing:
            found.append(
                Violation(
                    kind=ViolationKind.OPEN_WITHOUT_FLOW,
                    control_step=control_step,
                    well=well,
                    value=target.setpoint,
                    detail=(
                        f"the schedule keeps the well open with setpoint "
                        f"{target.setpoint} m3/day, the response gives a zero "
                        f"rate; control mode "
                        f"{state.active_control_mode.value}"
                    ),
                )
            )
        elif not wants_open and flowing:
            found.append(
                Violation(
                    kind=ViolationKind.SHUT_WITH_FLOW,
                    control_step=control_step,
                    well=well,
                    value=max(state.liquid_rate, state.injection_rate),
                    detail=(
                        "the schedule keeps the well shut, the response "
                        "gives a non-zero rate"
                    ),
                )
            )
    return tuple(found)


__all__ = [
    "check_intent_versus_fact",
]
