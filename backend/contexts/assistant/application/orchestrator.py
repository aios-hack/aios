from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator, Mapping, Sequence

from backend.contexts.assistant.application.answer import marker_position, split_answer
from backend.contexts.assistant.infrastructure.artifacts import ArtifactStore, RunStore
from backend.contexts.assistant.infrastructure.docs_index import DocsIndex
from backend.contexts.assistant.infrastructure.knowledge import Knowledge
from backend.contexts.assistant.infrastructure.prompt import build_system_prompt
from backend.contexts.assistant.domain.session import (
    Session,
    SessionStore,
    check_question,
)
from backend.contexts.assistant.infrastructure.session_store import SessionDisk
from backend.contexts.assistant.infrastructure.system_map import SystemMap
from backend.contexts.assistant.application.orchestrator_compose import (
    call_tool,
    compose,
    live_status,
)
from backend.contexts.assistant.application.orchestrator_events import (
    BRIEFING_QUESTION_EN,
    BRIEFING_QUESTION_RU,
    BRIEFING_TOOLS,
    DEFAULT_TIMEOUT,
    MAX_TOOL_ROUNDS,
    Cancelled,
    Event,
    stamp,
)
from backend.contexts.assistant.application.tools import tool_specs
from backend.contexts.assistant.application.tools.context import (
    Card,
    ConsoleContext,
    ToolContext,
)
from backend.contexts.assistant.infrastructure.llm.chat import ChatClient
from backend.contexts.assistant.infrastructure.llm.chat_events import (
    ChatMessage,
    Done,
    TextDelta,
    ToolCall,
)


class Orchestrator:
    def __init__(
        self,
        client: ChatClient,
        store: ArtifactStore,
        knowledge: Knowledge,
        sessions: SessionStore | None = None,
        max_rounds: int = MAX_TOOL_ROUNDS,
        timeout: float = DEFAULT_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        runs: RunStore | None = None,
        docs: DocsIndex | None = None,
        system: SystemMap | None = None,
        disk: SessionDisk | None = None,
        capabilities: Callable[[], dict[str, Any]] | None = None,
        now: Callable[[], str] = stamp,
    ) -> None:
        self._now = now
        self._client = client
        self._store = store
        self._knowledge = knowledge
        self._runs = runs
        self._docs = docs
        self._system = system
        self._disk = disk
        self._capabilities = capabilities
        self._sessions = (
            sessions
            if sessions is not None
            else SessionStore(disk=disk)
        )
        self._max_rounds = max_rounds
        self._timeout = timeout
        self._clock = clock

    @property
    def sessions(self) -> SessionStore:
        return self._sessions

    @property
    def disk(self) -> SessionDisk | None:
        return self._disk

    @property
    def docs(self) -> DocsIndex | None:
        return self._docs

    @property
    def system(self) -> SystemMap | None:
        return self._system

    @property
    def provider(self) -> str:
        return self._client.provider

    @property
    def model(self) -> str:
        return self._client.model

    def ask(
        self, session_id: str, question: str, console: ConsoleContext
    ) -> Iterator[Event]:
        text = check_question(question)
        session = self._sessions.start(session_id, console)
        started = self._clock()
        self._record(
            session_id,
            {
                "type": "ask",
                "question": text,
                "context": console.as_dict(),
                "ts": self._now(),
            },
            console.lang,
        )
        try:
            for event in self._run(session, text, console, started):
                self._record(session_id, event.as_dict(), console.lang)
                yield event
        except Cancelled:
            yield Event(
                "error",
                {
                    "code": "cancelled",
                    "message": (
                        "generation cancelled: a newer request arrived on the "
                        "same session or the client closed the connection"
                    ),
                },
            )
        finally:
            self._sessions.finish(session_id)

    def briefing(
        self, session_id: str, console: ConsoleContext
    ) -> Iterator[Event]:
        session = self._sessions.start(session_id, console)
        started = self._clock()
        question = (
            BRIEFING_QUESTION_EN if console.lang == "en" else BRIEFING_QUESTION_RU
        )
        try:
            yield from self._run(
                session, question, console, started, preset=BRIEFING_TOOLS
            )
        except Cancelled:
            yield Event(
                "error",
                {"code": "cancelled", "message": "briefing cancelled"},
            )
        finally:
            self._sessions.finish(session_id)

    def _record(
        self, session_id: str, body: Mapping[str, Any], lang: str
    ) -> None:
        if self._disk is None:
            return
        if body.get("type") in ("caption_delta", "answer_delta", "status"):
            return
        try:
            self._disk.append(session_id, body, lang)
        except Exception:
            return

    def _checkpoint(self, session: Session, started: float) -> None:
        if self._sessions.is_cancelled(session.session_id):
            raise Cancelled(session.session_id)
        if self._clock() - started > self._timeout:
            raise TimeoutError(
                f"Jarvis exceeded the {self._timeout:.0f} s budget for a single "
                "answer: the upstream model or a tool did not finish in time"
            )

    def _messages(self, session: Session, question: str) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        memory = session.summary()
        if memory:
            messages.append(
                ChatMessage(
                    role="user", content=f"Earlier in this session:\n{memory}"
                )
            )
        messages.append(ChatMessage(role="user", content=question))
        return messages

    def _context(self, console: ConsoleContext) -> ToolContext:
        return ToolContext(
            store=self._store,
            console=console,
            knowledge=self._knowledge,
            runs=self._runs,
            docs=self._docs,
            system=self._system,
        )

    def _live(self, context: ToolContext) -> dict[str, Any] | None:
        return live_status(context)

    def _run(
        self,
        session: Session,
        question: str,
        console: ConsoleContext,
        started: float,
        preset: Sequence[tuple[str, Mapping[str, Any]]] = (),
    ) -> Iterator[Event]:
        scene_id = session.next_scene_id()
        yield Event(
            "scene",
            {
                "scene_id": scene_id,
                "question": question,
                "context": console.as_dict(),
                "ts": self._now(),
                "session_id": session.session_id,
            },
        )
        if self._capabilities is not None:
            try:
                yield Event("capabilities", self._capabilities())
            except Exception:
                pass
        context = self._context(console)
        system = build_system_prompt(
            console,
            console.lang,
            system=self._system,
            live=self._live(context),
            memory=session.summary_text,
        )
        messages = self._messages(session, question)
        specs = tool_specs()
        cards: list[Card] = []
        order = 0
        rounds = 0
        deltas: list[str] = []
        for name, arguments in preset:
            self._checkpoint(session, started)
            yield Event("status", {"state": "tool", "tool": name})
            order += 1
            card, result = call_tool(context, ToolCall(id=f"p{order}", name=name, args=arguments))
            cards.append(card)
            yield Event(
                "card",
                {
                    "scene_id": scene_id,
                    "card_id": f"c-{order:02d}",
                    "order": order,
                    "tool": name,
                    "args": dict(arguments),
                    "card": card.as_dict(),
                },
            )
            messages.append(
                ChatMessage(
                    role="user",
                    content=f"Tool {name} returned: "
                    + json.dumps(result, ensure_ascii=False),
                )
            )
        while True:
            self._checkpoint(session, started)
            yield Event("status", {"state": "thinking"})
            calls: list[ToolCall] = []
            deltas = []
            in_answer = False
            final = rounds >= self._max_rounds
            for event in self._client.stream(messages, specs, system):
                self._checkpoint(session, started)
                if isinstance(event, TextDelta):
                    deltas.append(event.text)
                    if in_answer:
                        yield Event(
                            "answer_delta",
                            {"scene_id": scene_id, "text": event.text},
                        )
                        continue
                    joined = "".join(deltas)
                    if marker_position(joined) is None:
                        yield Event(
                            "caption_delta",
                            {"scene_id": scene_id, "text": event.text},
                        )
                        continue
                    in_answer = True
                    tail = split_answer(joined).answer or ""
                    if tail:
                        yield Event(
                            "answer_delta",
                            {"scene_id": scene_id, "text": tail},
                        )
                elif isinstance(event, ToolCall):
                    calls.append(event)
                elif isinstance(event, Done):
                    break
            if not calls or final:
                break
            rounds += 1
            messages.append(
                ChatMessage(role="assistant", content=None, tool_calls=tuple(calls))
            )
            for call in calls:
                self._checkpoint(session, started)
                yield Event("status", {"state": "tool", "tool": call.name})
                order += 1
                card, result = call_tool(context, call)
                cards.append(card)
                yield Event(
                    "card",
                    {
                        "scene_id": scene_id,
                        "card_id": f"c-{order:02d}",
                        "order": order,
                        "tool": call.name,
                        "args": dict(call.args),
                        "card": card.as_dict(),
                    },
                )
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=call.id,
                    )
                )
        yield from compose(
            self._client,
            self._store,
            self._disk,
            context,
            console,
            session,
            scene_id,
            question,
            messages,
            system,
            cards,
            deltas,
            rounds,
            int((self._clock() - started) * 1000),
        )
