"""canonical_schedule_hash и JCS-сериализация. README.md §1.6.

`canonical_bytes` — практическое приближение RFC 8785 (JSON Canonicalization
Scheme) средствами stdlib: ключи сортируются по code point (совпадает с
сортировкой по UTF-16 code units для ASCII-имён полей — других в проекте
нет), числа сериализует `json.dumps` (алгоритм кратчайшего round-trip,
как и в ECMAScript, но не гарантированно байт-в-байт идентичен на
экзотических случаях вроде экспоненциальной записи). Для полного
соответствия RFC 8785 при интеграции с внешними системами — заменить на
специализированный пакет (`rfc8785`/`jcs` на PyPI). Внутри проекта
свойство, которое реально нужно — детерминированность на своих же данных
(тот же вход даёт тот же хеш всегда), она этой реализацией гарантирована.

`content_hash_*` (README.md §6a) под это правило не попадает: считается
напрямую по байтам эмитированного файла, без разбора и канонизации —
см. `content_hash` в этом модуле.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from .schedule import ControlEvent, FixedDeckEvent, Schedule


def _to_jsonable(value: Any) -> Any:
    """Приводит значение к структуре, которую понимает json.dumps."""
    if isinstance(value, date):
        return value.isoformat()  # YYYY-MM-DD
    if hasattr(value, "value") and hasattr(value, "name") and not isinstance(value, (int, str)):
        # Enum
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {f: _to_jsonable(getattr(value, f)) for f in value.__dataclass_fields__}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def canonical_bytes(value: Any) -> bytes:
    """JCS-приближение: UTF-8 JSON, отсортированные ключи, без пробелов."""
    obj = _to_jsonable(value)
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text.encode("utf-8")


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


def schedule_hash(schedule: Schedule) -> str:
    """canonical_schedule_hash для готового Schedule целиком."""
    return canonical_schedule_hash(
        schedule.initial_state, schedule.fixed_deck_events, schedule.control_events
    )
