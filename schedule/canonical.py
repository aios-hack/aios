"""Канонизация Schedule и трёхсоставной canonical_schedule_hash.

Порядок событий, снятие точных дубликатов и отклонение конфликтов заданы
инвариантами 1 и 2 (`contracts/README.md` §2), формула хеша — §1.6.

`canonical_bytes` из `contracts.hashing` объявлен приближением RFC 8785:
`json.dumps` печатает вещественные по правилам Python (`1.0`, `1e-07`,
`-0.0`), а JCS требует ECMAScript `Number::toString` (`1`, `1e-7`, `0`).
Здесь сериализация чисел доведена до RFC 8785 без правки `contracts/`;
примитивы `contracts.hashing` (`content_hash`, `canonical_schedule_hash`)
переиспользуются как есть.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from datetime import date
from decimal import Decimal
from enum import Enum
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
    canonical_schedule_hash,
)

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


def _well_sort_key(well: str) -> tuple[int, int, str]:
    return (0, int(well), well) if well.isdigit() else (1, 0, well)


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


def ecmascript_number(value: float | int) -> str:
    """Number::toString по ECMAScript, как требует RFC 8785 §3.2.2.3."""

    if isinstance(value, bool):
        raise ScheduleCanonicalError("булево не является числом JCS")
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        raise ScheduleCanonicalError(f"JCS не сериализует {value}")
    if value == 0.0:
        return "0"
    if value < 0:
        return "-" + ecmascript_number(-value)
    if float(value).is_integer() and abs(value) < 1e21:
        return str(int(value))

    digits, exponent = _shortest_digits(value)
    k = len(digits)
    n = exponent + k
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    sign = "+" if n - 1 >= 0 else "-"
    return f"{mantissa}e{sign}{abs(n - 1)}"


def _shortest_digits(value: float) -> tuple[str, int]:
    text = repr(float(value))
    mantissa, _, exponent_text = text.partition("e")
    exponent = int(exponent_text) if exponent_text else 0
    integer_part, _, fraction_part = mantissa.partition(".")
    digits = (integer_part + fraction_part).lstrip("0")
    exponent -= len(fraction_part)
    stripped = digits.rstrip("0")
    exponent += len(digits) - len(stripped)
    return stripped or "0", exponent


def _escape(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _sort_key(name: str) -> tuple[int, ...]:
    return tuple(name.encode("utf-16-be"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "__dataclass_fields__"):
        return {name: _jsonable(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    raise ScheduleCanonicalError(f"тип {type(value).__name__} не сериализуется в JCS")


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return ecmascript_number(value)
    if isinstance(value, str):
        return _escape(value)
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, dict):
        names = sorted(value, key=_sort_key)
        return "{" + ",".join(f"{_escape(name)}:{_serialize(value[name])}" for name in names) + "}"
    raise ScheduleCanonicalError(f"тип {type(value).__name__} не сериализуется в JCS")


def canonical_bytes(value: Any) -> bytes:
    """RFC 8785 (JCS): UTF-8 без BOM, ключи по UTF-16, числа по ECMAScript."""

    return _serialize(_jsonable(value)).encode("utf-8")


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
