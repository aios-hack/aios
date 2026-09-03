from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.knowledge import Knowledge
from backend.application.jarvis.orchestrator import Event, Orchestrator
from backend.application.jarvis.session import SessionStore
from backend.application.jarvis.tools.context import ConsoleContext
from backend.infrastructure.llm.chat_events import ToolCall
from backend.infrastructure.llm.fake_chat import FakeChatClient

FIXTURE_DIR = Path("frontend") / "public" / "jarvis" / "fixtures"


@dataclass(frozen=True, slots=True)
class Recording:
    name: str
    question: str
    console: ConsoleContext
    calls: tuple[Mapping[str, object], ...]
    caption: str


def _tool_calls(calls: Sequence[Mapping[str, object]]) -> list[ToolCall]:
    return [
        ToolCall(
            id=f"call_{position + 1:02d}",
            name=str(entry["name"]),
            args=dict(entry.get("args") or {}),
        )
        for position, entry in enumerate(calls)
    ]


def replay(
    recording: Recording, store: ArtifactStore, knowledge: Knowledge
) -> Iterator[Event]:
    client = FakeChatClient(
        rounds=[_tool_calls(recording.calls)], caption=recording.caption
    )
    orchestrator = Orchestrator(
        client=client,
        store=store,
        knowledge=knowledge,
        sessions=SessionStore(),
        clock=_frozen_clock(),
    )
    return orchestrator.ask(
        f"fixture-{recording.name}", recording.question, recording.console
    )


def _frozen_clock() -> "Clock":
    return Clock()


class Clock:
    def __init__(self, step: float = 0.512) -> None:
        self._value = 0.0
        self._step = step

    def __call__(self) -> float:
        current = self._value
        self._value += self._step
        return current


def to_jsonl(events: Iterable[Event]) -> str:
    lines = [
        json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True)
        for event in events
    ]
    return "\n".join(lines) + "\n"


def write(
    recordings: Sequence[Recording],
    store: ArtifactStore,
    knowledge: Knowledge,
    root: Path,
) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for recording in recordings:
        path = root / f"{recording.name}.jsonl"
        path.write_text(
            to_jsonl(replay(recording, store, knowledge)), encoding="utf-8"
        )
        written.append(path)
    return written
