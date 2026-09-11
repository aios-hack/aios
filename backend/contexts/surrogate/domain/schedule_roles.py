"""Role timeline shared by data preparation code.

The response loader reconstructs only availability, operating status, and
setpoint.  Role has a separate lifecycle: a well can be commissioned by the
immutable fixed layer and a producer can later be converted to injection by a
managed event.  Keeping that logic explicit prevents consumers from assuming
that the response loader's private timeline exposes a role method.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from backend.core.contracts import EventKind, Role, Schedule


@dataclass(frozen=True, slots=True)
class RoleTimeline:
    steps: tuple[int, ...]
    values: tuple[Role, ...]

    def role(self, control_step: int) -> Role:
        index = bisect_right(self.steps, control_step) - 1
        return self.values[index] if index >= 0 else Role.NONE


def build_role_timelines(schedule: Schedule) -> dict[str, RoleTimeline]:
    wells = (
        set(schedule.meta.wells)
        | set(schedule.initial_state)
        | {event.well for event in schedule.fixed_deck_events}
        | {event.well for event in schedule.control_events}
    )
    changes: dict[str, list[tuple[int, int, Role]]] = {well: [] for well in wells}
    for event in schedule.fixed_deck_events:
        if event.operator == "WCONPROD":
            changes[event.well].append((event.control_step, 0, Role.PROD))
        elif event.operator == "WCONINJE":
            changes[event.well].append((event.control_step, 0, Role.INJ))
    for event in schedule.control_events:
        if event.kind is EventKind.CONVERT_INJ:
            # Managed events are emitted after the immutable fixed layer at
            # the same control step, so conversion wins any same-step tie.
            changes[event.well].append((event.control_step, 1, Role.INJ))

    timelines: dict[str, RoleTimeline] = {}
    for well in wells:
        initial = schedule.initial_state.get(well)
        points = [(-1, -1, Role.NONE if initial is None else initial.role)]
        points.extend(changes[well])
        points.sort(key=lambda item: (item[0], item[1]))
        timelines[well] = RoleTimeline(
            steps=tuple(step for step, _, _ in points),
            values=tuple(role for _, _, role in points),
        )
    return timelines
