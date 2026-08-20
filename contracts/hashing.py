"""canonical_schedule_hash и JCS-сериализация. README.md §1.6.

`canonical_bytes` — RFC 8785 (JSON Canonicalization Scheme) целиком, а не
приближение: имена свойств сортируются по UTF-16 code units, числа
печатаются по `Number::toString` ECMAScript (`45.0` → `45`, `1e-07` →
`1e-7`, `-0.0` → `0`), незначащих пробелов нет, кодировка UTF-8 без BOM.

**Задача G2, 20.08.** До этой даты здесь стоял `json.dumps(sort_keys=True)`,
объявленный «практическим приближением» RFC 8785, а строгая реализация
жила отдельно в `schedule/canonical.py`. Два сериализатора давали разный
`canonical_schedule_hash` на одном и том же расписании, то есть величина,
которую §1.6 называет единственной, единственной не была. Канон проекта —
строгий JCS: так написано в §1.6 с самого начала, приближение было
отступлением от собственного контракта. Строгая реализация перенесена сюда,
`schedule/canonical.py` теперь переиспользует её, а не дублирует.

Тем же заходом закрыт дефект приближения, найденный задачей 53: ключ
словаря приводился к JSON-совместимому виду только сортировкой, поэтому
`canonical_bytes(config)` падал на `Config.rules: dict[Rule, bool]` с
«'<' not supported between instances of 'Rule' and 'Rule'». Ключи
приводятся к строкам явно (`_key_text`), включая enum, даты и числа.

`content_hash_*` (README.md §6a) под это правило не попадает: считается
напрямую по байтам эмитированного файла, без разбора и канонизации —
см. `content_hash` в этом модуле.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from .schedule import ControlEvent, FixedDeckEvent, Schedule, utf16_code_units


class CanonicalizationError(ValueError):
    """Значение не сериализуется по RFC 8785: чужой тип, NaN, Infinity."""


def ecmascript_number(value: float | int) -> str:
    """`Number::toString` по ECMAScript, как требует RFC 8785 §3.2.2.3.

    Отличия от `repr`/`json.dumps` Python, из-за которых приближение и
    давало другой хеш: целые вещественные печатаются без дробной части
    (`45.0` → `45`), экспонента без ведущего нуля (`1e-07` → `1e-7`),
    отрицательный ноль сходится с положительным (`-0.0` → `0`).
    """

    if isinstance(value, bool):
        raise CanonicalizationError("булево не является числом JCS")
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        raise CanonicalizationError(f"JCS не сериализует {value}")
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
    """Кратчайшая round-trip запись: значащие цифры и десятичный порядок."""

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
    """Ключ объекта JSON — всегда строка (RFC 8785 §3.2.3).

    Enum в позиции ключа — не экзотика, а `Config.rules: dict[Rule, bool]`;
    приближение на нём падало, потому что сортировало ключи как есть.
    """

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
        f"ключ типа {type(key).__name__} не сериализуется в JCS"
    )


def _jsonable(value: Any) -> Any:
    """Приводит значение к структуре, которую понимает `_serialize`."""

    if isinstance(value, date):
        return value.isoformat()  # YYYY-MM-DD
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
                    f"ключи {key!r} и другой ключ дают одно имя {name!r}: "
                    "канонизация была бы неоднозначной"
                )
            items[name] = _jsonable(item)
        return items
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    raise CanonicalizationError(f"тип {type(value).__name__} не сериализуется в JCS")


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
    raise CanonicalizationError(f"тип {type(value).__name__} не сериализуется в JCS")


def canonical_bytes(value: Any) -> bytes:
    """RFC 8785 (JCS): UTF-8 без BOM, ключи по UTF-16, числа по ECMAScript."""

    return _serialize(_jsonable(value)).encode("utf-8")


def content_hash(raw_bytes: bytes) -> str:
    """Хеш байтов эмитированного файла напрямую, без канонизации (§6a)."""
    return hashlib.sha256(raw_bytes).hexdigest()


def _digest(value: Any) -> bytes:
    return hashlib.sha256(canonical_bytes(value)).digest()


def canonical_schedule_hash(
    history_prefix: Any,
    fixed_deck_events: tuple[FixedDeckEvent, ...] | list[FixedDeckEvent],
    control_events: tuple[ControlEvent, ...] | list[ControlEvent],
) -> str:
    """SHA256(SHA256(prefix) ‖ SHA256(fixed) ‖ SHA256(control)). README.md §1.6.

    `‖` — конкатенация трёх 32-байтных дайджестов в фиксированном порядке
    (история, фиксированные события, управляющие события), не hex-строк.
    Единственное имя этой величины в проекте — не «хеш дека», не «хеш
    файла», не `schedule_hash` без уточнения.
    """
    digest = hashlib.sha256(
        _digest(history_prefix) + _digest(list(fixed_deck_events)) + _digest(list(control_events))
    ).hexdigest()
    return digest


def hash_schedule(schedule: Schedule) -> str:
    """canonical_schedule_hash для готового Schedule целиком.

    Названо `hash_schedule`, не `schedule_hash` — второе запрещено §1.6
    (единственное имя величины — `canonical_schedule_hash`, без
    сокращений и синонимов).
    """
    return canonical_schedule_hash(
        schedule.initial_state, schedule.fixed_deck_events, schedule.control_events
    )
