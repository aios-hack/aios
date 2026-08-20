"""Канонизация Schedule и трёхсоставной canonical_schedule_hash.

Порядок событий, снятие точных дубликатов и отклонение конфликтов заданы
инвариантами 1 и 2 (`contracts/README.md` §2), формула хеша — §1.6.

**Задача G2, 20.08.** До этой даты здесь была отдельная строгая
реализация RFC 8785 (JCS), потому что `contracts.hashing.canonical_bytes`
считался приближением. Приближения больше нет: `contracts.hashing` сам —
строгий JCS, этот модуль его переиспользует, а не дублирует.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from typing import Any, Mapping, Sequence

from contracts import (
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    OperatingStatus,
    Role,
    Schedule,
    WellState,
    canonical_bytes,
    canonical_schedule_hash,
)
from contracts.hashing import ecmascript_number

_KIND_RANK: dict[EventKind, int] = {
    EventKind.CONVERT_INJ: 0,
    EventKind.SET_LRAT: 1,
    EventKind.SET_RATE: 1,
    EventKind.OPEN: 2,
    EventKind.SHUT: 2,
}

_HASH_HEX_LENGTH = 64
_DIGEST_BYTES = 32


class ScheduleCanonicalError(ValueError):
    """Расписание не канонизируется: конфликтующие события или битое состояние."""


def _well_sort_key(well: str) -> str:
    """Лексикографический порядок — канон `bridge.OpmDeckEmitter.source_wells`."""
    return well


def _control_event_key(event: ControlEvent) -> tuple[int, tuple[int, int, str], int, str]:
    return (
        event.control_step,
        _well_sort_key(event.well),
        _KIND_RANK[event.kind],
        event.kind.name,
    )


def _fixed_event_key(
    index: int, event: FixedDeckEvent
) -> tuple[int, int]:
    return (event.control_step, index)


def canonical_digest(value: Any) -> bytes:
    return hashlib.sha256(canonical_bytes(value)).digest()


def canonical_part_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize_well_state(state: WellState) -> WellState:
    """Невведённая скважина всегда role=NONE, SHUT, 0.0 (§2 «Состояние скважины»)."""

    if state.availability is Availability.NOT_COMMISSIONED:
        if (
            state.role is Role.NONE
            and state.operating_status is OperatingStatus.SHUT
            and state.setpoint == 0.0
        ):
            return state
        return WellState(
            availability=Availability.NOT_COMMISSIONED,
            role=Role.NONE,
            operating_status=OperatingStatus.SHUT,
            setpoint=0.0,
        )
    if state.setpoint == 0.0 and math.copysign(1.0, state.setpoint) < 0:
        return replace(state, setpoint=0.0)
    return state


def normalize_initial_state(
    initial_state: Mapping[str, WellState], wells: Sequence[str] | None = None
) -> dict[str, WellState]:
    axis = tuple(wells) if wells is not None else tuple(
        sorted(initial_state, key=_well_sort_key)
    )
    missing = [well for well in axis if well not in initial_state]
    if missing:
        raise ScheduleCanonicalError(f"в initial_state нет скважин оси: {missing}")
    extra = [well for well in initial_state if well not in set(axis)]
    if extra:
        raise ScheduleCanonicalError(f"initial_state содержит скважины вне оси: {sorted(extra)}")
    return {well: normalize_well_state(initial_state[well]) for well in axis}


def find_control_conflicts(
    events: Sequence[ControlEvent],
) -> tuple[tuple[int, str, EventKind, tuple[float | None, ...]], ...]:
    seen: dict[tuple[int, str, EventKind], list[float | None]] = {}
    for event in events:
        values = seen.setdefault((event.control_step, event.well, event.kind), [])
        if event.value not in values:
            values.append(event.value)
    conflicts = [
        (step, well, kind, tuple(values))
        for (step, well, kind), values in seen.items()
        if len(values) > 1
    ]
    conflicts.sort(key=lambda item: (item[0], _well_sort_key(item[1]), item[2].name))
    return tuple(conflicts)


def canonicalize_control_events(
    events: Sequence[ControlEvent],
) -> tuple[ControlEvent, ...]:
    conflicts = find_control_conflicts(events)
    if conflicts:
        step, well, kind, values = conflicts[0]
        raise ScheduleCanonicalError(
            f"конфликтующие управляющие события: скважина {well!r}, "
            f"control_step={step}, {kind.name}, значения {values}"
        )
    unique: dict[tuple[int, str, EventKind, float | None], ControlEvent] = {}
    for event in events:
        unique.setdefault((event.control_step, event.well, event.kind, event.value), event)
    return tuple(sorted(unique.values(), key=_control_event_key))


def canonicalize_fixed_events(
    events: Sequence[FixedDeckEvent],
) -> tuple[FixedDeckEvent, ...]:
    """Порядок фиксированного слоя — исходный порядок дека внутри шага (§1.6)."""

    indexed = list(enumerate(events))
    indexed.sort(key=lambda item: _fixed_event_key(item[0], item[1]))
    return tuple(event for _, event in indexed)


def canonicalize(schedule: Schedule) -> Schedule:
    """Каноническое расписание: нормализованные состояния и оба слоя в порядке §2."""

    wells = schedule.meta.wells or tuple(sorted(schedule.initial_state, key=_well_sort_key))
    initial_state = normalize_initial_state(schedule.initial_state, wells)
    control_events = canonicalize_control_events(schedule.control_events)
    fixed_deck_events = canonicalize_fixed_events(schedule.fixed_deck_events)
    meta = replace(
        schedule.meta,
        wells=wells,
        history_prefix_hash=canonical_part_hash(initial_state),
        fixed_events_hash=canonical_part_hash(list(fixed_deck_events)),
        control_events_hash=canonical_part_hash(list(control_events)),
    )
    return Schedule(
        meta=meta,
        initial_state=initial_state,
        fixed_deck_events=fixed_deck_events,
        control_events=control_events,
    )


def canonical_hash_parts(schedule: Schedule) -> tuple[str, str, str]:
    canonical = canonicalize(schedule)
    return (
        canonical.meta.history_prefix_hash,
        canonical.meta.fixed_events_hash,
        canonical.meta.control_events_hash,
    )


def hash_canonical_schedule(schedule: Schedule) -> str:
    """SHA256(SHA256(part1) ‖ SHA256(part2) ‖ SHA256(part3)) на сырых дайджестах."""

    canonical = canonicalize(schedule)
    digest = hashlib.sha256(
        canonical_digest(canonical.initial_state)
        + canonical_digest(list(canonical.fixed_deck_events))
        + canonical_digest(list(canonical.control_events))
    ).hexdigest()
    if len(digest) != _HASH_HEX_LENGTH:
        raise ScheduleCanonicalError(f"хеш не {_HASH_HEX_LENGTH} hex-символов: {digest}")
    return digest


def hash_parts_raw(
    history_prefix: Any,
    fixed_deck_events: Sequence[FixedDeckEvent],
    control_events: Sequence[ControlEvent],
) -> str:
    digests = (
        canonical_digest(history_prefix),
        canonical_digest(list(fixed_deck_events)),
        canonical_digest(list(control_events)),
    )
    for digest in digests:
        if len(digest) != _DIGEST_BYTES:
            raise ScheduleCanonicalError("часть хеша не 32 байта")
    return hashlib.sha256(b"".join(digests)).hexdigest()


def contracts_hash(schedule: Schedule) -> str:
    canonical = canonicalize(schedule)
    return canonical_schedule_hash(
        canonical.initial_state, canonical.fixed_deck_events, canonical.control_events
    )
