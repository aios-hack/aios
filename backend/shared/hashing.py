from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Sequence


class CanonicalizationError(ValueError):
    pass


def utf16_code_units(text: str) -> tuple[int, ...]:
    units: list[int] = []
    for char in text:
        code_point = ord(char)
        if code_point <= 0xFFFF:
            units.append(code_point)
        else:
            code_point -= 0x10000
            units.append(0xD800 + (code_point >> 10))
            units.append(0xDC00 + (code_point & 0x3FF))
    return tuple(units)


def ecmascript_number(value: float | int) -> str:
    if isinstance(value, bool):
        raise CanonicalizationError("a boolean is not a JCS number")
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        raise CanonicalizationError(f"JCS does not serialize {value}")
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


def _key_text(key: Any) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, Enum):
        return key.value if isinstance(key.value, str) else _key_text(key.value)
    if isinstance(key, date):
        return key.isoformat()
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, (int, float)):
        return ecmascript_number(key)
    if isinstance(key, Decimal):
        return ecmascript_number(float(key))
    raise CanonicalizationError(
        f"a key of type {type(key).__name__} is not serializable to JCS"
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "__dataclass_fields__"):
        return {name: _jsonable(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, Mapping):
        items: dict[str, Any] = {}
        for key, item in value.items():
            name = _key_text(key)
            if name in items:
                raise CanonicalizationError(
                    f"key {key!r} and another key produce the same name {name!r}: "
                    "canonicalization would be ambiguous"
                )
            items[name] = _jsonable(item)
        return items
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    raise CanonicalizationError(f"type {type(value).__name__} is not serializable to JCS")


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
        names = sorted(value, key=utf16_code_units)
        return "{" + ",".join(f"{_escape(name)}:{_serialize(value[name])}" for name in names) + "}"
    raise CanonicalizationError(f"type {type(value).__name__} is not serializable to JCS")


def canonical_bytes(value: Any) -> bytes:
    return _serialize(_jsonable(value)).encode("utf-8")


def content_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _digest(value: Any) -> bytes:
    return hashlib.sha256(canonical_bytes(value)).digest()


def canonical_schedule_hash(
    history_prefix: Any,
    fixed_deck_events: Sequence[Any],
    control_events: Sequence[Any],
) -> str:
    return hashlib.sha256(
        _digest(history_prefix) + _digest(list(fixed_deck_events)) + _digest(list(control_events))
    ).hexdigest()


def hash_schedule(schedule: Any) -> str:
    return canonical_schedule_hash(
        schedule.initial_state, schedule.fixed_deck_events, schedule.control_events
    )


__all__ = [
    "CanonicalizationError",
    "canonical_bytes",
    "canonical_hash",
    "canonical_schedule_hash",
    "content_hash",
    "ecmascript_number",
    "hash_schedule",
    "utf16_code_units",
]
