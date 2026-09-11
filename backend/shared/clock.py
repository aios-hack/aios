from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def advance(self, seconds: float) -> None:
        self._moment = datetime.fromtimestamp(
            self._moment.timestamp() + seconds, tz=self._moment.tzinfo
        )


__all__ = ["Clock", "FrozenClock", "SystemClock"]
