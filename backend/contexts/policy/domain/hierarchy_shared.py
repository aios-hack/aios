from __future__ import annotations

from typing import (
    Sequence,
)
from backend.contexts.schedule.domain.schedule import ControlEvent, EventKind
from backend.contexts.connectivity.domain.connectivity import Groups
from backend.contexts.policy.domain.state import (
    PolicyState,
    WellObservation,
)


FIELD_AGENT = "field"


WELL_LIMIT_TOLERANCE_M3_PER_DAY = 1e-9


def group_of(groups: Groups, well: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            group_id
            for group_id, wells in groups.groups.items()
            if well in wells
        )
    )


def restrict(state: PolicyState, wells: Sequence[str]) -> PolicyState:
    inside = {well: state.wells[well] for well in wells if well in state.wells}
    return PolicyState(control_step=state.control_step, wells=inside)


PRODUCTION_FLOOR_UNREACHABLE = "PRODUCTION_FLOOR_UNREACHABLE"


PRODUCTION_FLOOR_NOT_SET = "PRODUCTION_FLOOR_NOT_SET"


PRODUCTION_FLOOR_MET = "PRODUCTION_FLOOR_MET"


def wells_without_group(groups: Groups, wells: Sequence[str]) -> tuple[str, ...]:
    covered = {well for members in groups.groups.values() for well in members}
    return tuple(sorted(well for well in wells if well not in covered))


def observations_by_group(
    state: PolicyState, groups: Groups
) -> dict[str, tuple[WellObservation, ...]]:
    collected: dict[str, tuple[WellObservation, ...]] = {}
    for group_id in sorted(groups.groups):
        collected[group_id] = tuple(
            state.wells[well]
            for well in sorted(groups.groups[group_id])
            if well in state.wells
        )
    return collected


__all__ = [
    "FIELD_AGENT",
    "PRODUCTION_FLOOR_MET",
    "PRODUCTION_FLOOR_NOT_SET",
    "PRODUCTION_FLOOR_UNREACHABLE",
    "WELL_LIMIT_TOLERANCE_M3_PER_DAY",
    "group_of",
    "observations_by_group",
    "restrict",
    "wells_without_group",
]
