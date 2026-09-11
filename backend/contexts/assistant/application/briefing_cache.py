from __future__ import annotations

from typing import Any, Callable

BRIEFING_TTL = 60.0

BriefingKey = tuple[str, int, str]


class BriefingCache:
    def __init__(
        self,
        clock: Callable[[], float],
        ttl: float = BRIEFING_TTL,
    ) -> None:
        self._clock = clock
        self._ttl = ttl
        self._entries: dict[BriefingKey, tuple[float, list[dict[str, Any]]]] = {}

    @property
    def ttl(self) -> float:
        return self._ttl

    def get(self, key: BriefingKey) -> list[dict[str, Any]] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock() - entry[0] >= self._ttl:
            return None
        return entry[1]

    def put(self, key: BriefingKey, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._entries[key] = (self._clock(), events)
        return events

    def clear(self) -> None:
        self._entries.clear()


__all__ = ["BRIEFING_TTL", "BriefingCache", "BriefingKey"]
