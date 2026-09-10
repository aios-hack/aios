from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Mapping, Sequence

from backend.application.jarvis.answer import marker_position, split_answer
from backend.application.jarvis.artifacts import (
    ArtifactStore,
    RunError,
    RunStore,
)
from backend.application.jarvis.caption import (
    code_sources,
    doc_numbers,
    guard_answer_text,
    guard_with_retry,
)
from backend.application.jarvis.docs_index import DocsIndex
from backend.application.jarvis.knowledge import Knowledge
from backend.application.jarvis.prompt import build_system_prompt
from backend.application.jarvis.session import (
    Exchange,
    Session,
    SessionStore,
    check_question,
    summary_request,
)
from backend.application.jarvis.session_store import SessionDisk
from backend.application.jarvis.suggestions import build_suggestions
from backend.application.jarvis.system_map import SystemMap
from backend.application.jarvis.tools import error_card, run_tool, tool_specs
from backend.application.jarvis.tools.context import (
    Card,
    ConsoleContext,
    ToolContext,
    ToolFailure,
)
from backend.application.jarvis.tools.registry import ToolInputError
from backend.infrastructure.llm.chat import ChatClient
from backend.infrastructure.llm.chat_events import (
    ChatMessage,
    Done,
    TextDelta,
    ToolCall,
)

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
        try:
            card = run_tool("system_status", context, {})
        except Exception:
            return None
        return dict(card.payload)

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
            card, result = self._call(context, ToolCall(id=f"p{order}", name=name, args=arguments))
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
                card, result = self._call(context, call)
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
        yield Event("status", {"state": "composing"})
        payloads = [dict(card.payload) for card in cards]
        evidence = (*self._evidence(context), *doc_numbers(payloads))
        split = split_answer("".join(deltas))
        guarded = guard_with_retry(
            self._client, messages, system, split.caption, payloads, evidence
        )
        if guarded.warning is not None:
            yield Event("warning", guarded.warning)
        yield Event(
            "caption",
            {"scene_id": scene_id, "text": guarded.result.text, "guarded": True},
        )
        answer_text = ""
        if split.answer:
            checked = guard_answer_text(
                split.answer, payloads, evidence, code_sources(payloads)
            )
            for warning in checked.warnings:
                yield Event("warning", warning)
            answer_text = checked.text
            if answer_text:
                yield Event(
                    "answer",
                    {
                        "scene_id": scene_id,
                        "text": answer_text,
                        "guarded": True,
                    },
                )
        session.remember(
            Exchange(
                question=question,
                card_types=tuple(card.type for card in cards),
                caption=guarded.result.text,
                answer=answer_text,
            )
        )
        self._compress(session, system)
        yield Event(
            "suggestions", {"items": build_suggestions(console, self._store)}
        )
        yield Event(
            "done",
            {
                "scene_id": scene_id,
                "tool_rounds": rounds,
                "elapsed_ms": int((self._clock() - started) * 1000),
            },
        )

    def _compress(self, session: Session, system: str) -> None:
        pending = session.pending_summary()
        if not pending:
            return
        request = summary_request(pending)
        if session.summary_text:
            request = (
                f"Прежняя справка: {session.summary_text}\n\n{request}"
            )
        collected: list[str] = []
        try:
            for event in self._client.stream(
                [ChatMessage(role="user", content=request)], (), system
            ):
                if isinstance(event, TextDelta):
                    collected.append(event.text)
                elif isinstance(event, Done):
                    break
        except Exception:
            session.absorb_summary(session.summary_text)
            return
        session.absorb_summary("".join(collected).strip())
        if self._disk is not None and session.summary_text:
            try:
                self._disk.set_summary(session.session_id, session.summary_text)
            except Exception:
                return

    def _evidence(self, context: ToolContext) -> tuple[Any, ...]:
        try:
            record = context.run_store().read()
        except (ToolFailure, RunError):
            return ()
        return record.documents()

    def _call(self, context: ToolContext, call: ToolCall) -> tuple[Card, Any]:
        try:
            card = run_tool(call.name, context, call.args)
        except (ToolFailure, ToolInputError) as error:
            return error_card(call.name, str(error), context.lang), {
                "error": str(error)
            }
        except Exception as error:
            return error_card(call.name, str(error), context.lang), {
                "error": str(error)
            }
        return card, dict(card.payload)
