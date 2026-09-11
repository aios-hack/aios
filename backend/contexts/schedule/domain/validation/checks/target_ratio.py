from __future__ import annotations

from backend.contexts.schedule.domain.validation.interpreter import (
    _states_by_step,
    _target_at,
    _target_timeline,
)
from backend.contexts.schedule.domain.validation.report import (
    ACHIEVEMENT_THRESHOLD,
    TargetRatio,
)
from collections.abc import (
    Sequence,
)
from backend.contexts.schedule.domain.schedule import OperatingStatus, Role, Schedule
from backend.contexts.reservoir.domain.response import StateAtDate
from backend.contexts.schedule.domain.validate import (
    Violation,
    ViolationKind,
    _well_sort_key,
)


def check_target_ratio(
    schedule: Schedule,
    states: Sequence[StateAtDate],
) -> tuple[tuple[Violation, ...], tuple[TargetRatio, ...]]:
    timelines = _target_timeline(schedule)
    indexed = _states_by_step(states)
    found: list[Violation] = []
    ratios: list[TargetRatio] = []
    for (control_step, well), state in sorted(
        indexed.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        timeline = timelines.get(well)
        if timeline is None:
            continue
        target = _target_at(timeline, control_step)
        if not target.commissioned:
            continue
        if target.operating_status is OperatingStatus.SHUT:
            continue
        if target.setpoint <= 0.0:
            continue
        actual = (
            state.injection_rate if target.role is Role.INJ else state.liquid_rate
        )
        ratio = TargetRatio(
            control_step=control_step,
            well=well,
            role=target.role,
            target=target.setpoint,
            actual=actual,
            mode=state.active_control_mode,
        )
        ratios.append(ratio)
        if not ratio.achieved:
            found.append(
                Violation(
                    kind=ViolationKind.TARGET_UNDERSHOOT,
                    control_step=control_step,
                    well=well,
                    value=ratio.ratio,
                    detail=(
                        f"fact/target {ratio.ratio:.4f} < "
                        f"{ACHIEVEMENT_THRESHOLD}: fact {actual} m3/day "
                        f"against target {target.setpoint} m3/day, control "
                        f"mode {state.active_control_mode.value}"
                    ),
                )
            )
    return tuple(found), tuple(ratios)


__all__ = [
    "check_target_ratio",
]
