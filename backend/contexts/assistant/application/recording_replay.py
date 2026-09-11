from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from backend.contexts.assistant.application.answer import ANSWER_MARKER
from backend.contexts.assistant.infrastructure.artifacts import ArtifactStore
from backend.contexts.assistant.infrastructure.docs_index import DocsIndex
from backend.contexts.assistant.infrastructure.knowledge import Knowledge
from backend.contexts.assistant.application.orchestrator import Event, Orchestrator
from backend.contexts.assistant.domain.session import SessionStore
from backend.contexts.assistant.infrastructure.system_map import SystemMap
from backend.contexts.assistant.application.tools.context import ConsoleContext
from backend.contexts.assistant.infrastructure.llm.chat_events import ToolCall
from backend.contexts.assistant.infrastructure.llm.fake_chat import FakeChatClient

FIXTURE_DIR = Path("frontend") / "public" / "jarvis" / "fixtures"
FIXTURE_TS = "2026-09-11T00:00:00Z"


@dataclass(frozen=True, slots=True)
class Recording:
    name: str
    question: str
    console: ConsoleContext
    calls: tuple[Mapping[str, object], ...]
    caption: str
    answer: str = ""


def _tool_calls(calls: Sequence[Mapping[str, object]]) -> list[ToolCall]:
    return [
        ToolCall(
            id=f"call_{position + 1:02d}",
            name=str(entry["name"]),
            args=dict(entry.get("args") or {}),
        )
        for position, entry in enumerate(calls)
    ]


def _reply(recording: Recording) -> str:
    if not recording.answer:
        return recording.caption
    return f"{recording.caption}\n{ANSWER_MARKER}\n{recording.answer}"


def replay(
    recording: Recording,
    store: ArtifactStore,
    knowledge: Knowledge,
    docs: DocsIndex | None = None,
    system: SystemMap | None = None,
) -> Iterator[Event]:
    rounds = [_tool_calls(recording.calls)] if recording.calls else []
    client = FakeChatClient(rounds=rounds, caption=_reply(recording))
    orchestrator = Orchestrator(
        client=client,
        store=store,
        knowledge=knowledge,
        sessions=SessionStore(),
        docs=docs,
        system=system,
        clock=_frozen_clock(),
        now=lambda: FIXTURE_TS,
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
    docs: DocsIndex | None = None,
    system: SystemMap | None = None,
) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for recording in recordings:
        path = root / f"{recording.name}.jsonl"
        path.write_text(
            to_jsonl(replay(recording, store, knowledge, docs, system)),
            encoding="utf-8",
        )
        written.append(path)
    return written
