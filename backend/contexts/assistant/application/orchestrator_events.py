from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


MAX_TOOL_ROUNDS = 5


DEFAULT_TIMEOUT = 60.0


BRIEFING_TOOLS: tuple[tuple[str, Mapping[str, Any]], ...] = (
    ("system_status", {}),
    ("find_patterns", {"limit": 2}),
)


BRIEFING_QUESTION_RU = (
    "Опиши одной-двумя фразами состояние системы: чемпион, последний прогон, "
    "текущий шаг и тревоги диагностики. Только по данным карточек."
)


BRIEFING_QUESTION_EN = (
    "Describe the state of the system in one or two sentences: the champion, "
    "the latest run, the current step and the diagnostic alerts. Only from the "
    "card data."
)


class Cancelled(RuntimeError):
    pass


def stamp() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    body: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.body}
