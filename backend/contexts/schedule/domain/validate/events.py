from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from backend.contexts.schedule.domain.schedule import ControlEvent, EventKind

_COMMISSIONING_OPERATORS: frozenset[str] = frozenset({"WCONPROD", "WCONINJE"})


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    control_step: int
    well: str
    kind: EventKind
    value: float | None = None


def _well_sort_key(well: str) -> tuple[int, int, str]:
    return (0, int(well), well) if well.isdigit() else (1, 0, well)


def _event_sort_key(event: CandidateEvent) -> tuple[int, tuple[int, int, str], str]:
    return (event.control_step, _well_sort_key(event.well), event.kind.name)


def as_candidate(event: ControlEvent | CandidateEvent) -> CandidateEvent:
    if isinstance(event, CandidateEvent):
        return event
    return CandidateEvent(
        control_step=event.control_step,
        well=event.well,
        kind=event.kind,
        value=event.value,
    )


def candidates(
    events: Iterable[ControlEvent | CandidateEvent],
) -> tuple[CandidateEvent, ...]:
    return tuple(as_candidate(event) for event in events)
