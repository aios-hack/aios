from __future__ import annotations

from backend.contexts.schedule.domain.validation.interpreter import (
    _states_by_step,
    _target_at,
    _target_timeline,
)
from collections.abc import (
    Sequence,
)
from backend.contexts.schedule.domain.schedule import Role, Schedule
from backend.contexts.reservoir.domain.response import StateAtDate
from backend.contexts.schedule.domain.validate import (
    Violation,
    ViolationKind,
    _well_sort_key,
)


def check_role_consistency(
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
        if target.role is Role.INJ and state.liquid_rate > 0.0:
            found.append(
                Violation(
                    kind=ViolationKind.ROLE_FACT_MISMATCH,
                    control_step=control_step,
                    well=well,
                    value=state.liquid_rate,
                    detail=(
                        f"a well in the INJ role gives liquid production "
                        f"{state.liquid_rate} m3/day"
                    ),
                )
            )
        elif target.role is Role.PROD and state.injection_rate > 0.0:
            found.append(
                Violation(
                    kind=ViolationKind.ROLE_FACT_MISMATCH,
                    control_step=control_step,
                    well=well,
                    value=state.injection_rate,
                    detail=(
                        f"a well in the PROD role gives injection "
                        f"{state.injection_rate} m3/day"
                    ),
                )
            )
    return tuple(found)


__all__ = [
    "check_role_consistency",
]
