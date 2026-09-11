from __future__ import annotations

from backend.contexts.schedule.domain.validation.interpreter import (
    _states_by_step,
    _target_at,
    _target_timeline,
)
from backend.contexts.schedule.domain.validation.report import (
    ACHIEVEMENT_THRESHOLD,
)
from collections.abc import (
    Sequence,
)
from backend.contexts.reservoir.domain.response import ActiveControlMode, StateAtDate
from backend.contexts.schedule.domain.schedule import Role, Schedule
from backend.contexts.schedule.domain.validate import (
    Violation,
    ViolationKind,
    _well_sort_key,
)


def check_control_modes(
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
        mode = state.active_control_mode
        if mode is ActiveControlMode.UNKNOWN:
            found.append(
                Violation(
                    kind=ViolationKind.MODE_NOT_REPORTED,
                    control_step=control_step,
                    well=well,
                    value=None,
                    detail=(
                        "active_control_mode = UNKNOWN: the control mode "
                        "was not presented, the failure to reach the target "
                        "is unexplainable"
                    ),
                )
            )
            continue
        if not target.commissioned:
            if mode is not ActiveControlMode.NOT_COMMISSIONED:
                found.append(
                    Violation(
                        kind=ViolationKind.MODE_CONTRADICTS_SCHEDULE,
                        control_step=control_step,
                        well=well,
                        value=None,
                        detail=(
                            f"the schedule keeps the well not commissioned, "
                            f"the response gives {mode.value}"
                        ),
                    )
                )
            continue
        if mode is ActiveControlMode.NOT_COMMISSIONED:
            found.append(
                Violation(
                    kind=ViolationKind.MODE_CONTRADICTS_SCHEDULE,
                    control_step=control_step,
                    well=well,
                    value=None,
                    detail=(
                        "the response gives NOT_COMMISSIONED for a well "
                        "commissioned by the schedule"
                    ),
                )
            )
            continue
        if mode is ActiveControlMode.BHP_LIMITED:
            if target.setpoint <= 0.0:
                continue
            actual = (
                state.injection_rate if target.role is Role.INJ else state.liquid_rate
            )
            if actual / target.setpoint >= ACHIEVEMENT_THRESHOLD:
                found.append(
                    Violation(
                        kind=ViolationKind.BHP_LIMITED_WITHOUT_UNDERSHOOT,
                        control_step=control_step,
                        well=well,
                        value=actual / target.setpoint,
                        detail=(
                            "BHP_LIMITED mode while the target is reached: "
                            "a pressure limit is claimed, but there is no "
                            "shortfall"
                        ),
                    )
                )
    return tuple(found)


__all__ = [
    "check_control_modes",
]
