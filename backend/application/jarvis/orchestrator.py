from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.caption import guard_with_retry
from backend.application.jarvis.knowledge import Knowledge
from backend.application.jarvis.prompt import build_system_prompt
from backend.application.jarvis.session import (
    Exchange,
    Session,
    SessionStore,
    check_question,
)
from backend.application.jarvis.suggestions import build_suggestions
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

MAX_TOOL_ROUNDS = 4
DEFAULT_TIMEOUT = 60.0


class Cancelled(RuntimeError):
    pass


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
    ) -> None:
        self._client = client
        self._store = store
        self._knowledge = knowledge
        self._sessions = sessions if sessions is not None else SessionStore()
        self._max_rounds = max_rounds
        self._timeout = timeout
        self._clock = clock

    @property
    def sessions(self) -> SessionStore:
        return self._sessions

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
        try:
            yield from self._run(session, text, console, started)
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
        if session.history:
            messages.append(
                ChatMessage(
                    role="user",
                    content=f"Earlier in this session:\n{session.summary()}",
                )
            )
        messages.append(ChatMessage(role="user", content=question))
        return messages

    def _run(
        self,
        session: Session,
        question: str,
        console: ConsoleContext,
        started: float,
    ) -> Iterator[Event]:
        scene_id = session.next_scene_id()
        yield Event(
            "scene",
            {
                "scene_id": scene_id,
                "question": question,
                "context": console.as_dict(),
            },
        )
        context = ToolContext(
            store=self._store, console=console, knowledge=self._knowledge
        )
        system = build_system_prompt(console, console.lang)
        messages = self._messages(session, question)
        specs = tool_specs()
        cards: list[Card] = []
        order = 0
        rounds = 0
        deltas: list[str] = []
        while True:
            self._checkpoint(session, started)
            yield Event("status", {"state": "thinking"})
            calls: list[ToolCall] = []
            deltas = []
            final = rounds >= self._max_rounds
            for event in self._client.stream(messages, specs, system):
                self._checkpoint(session, started)
                if isinstance(event, TextDelta):
                    deltas.append(event.text)
                    yield Event(
                        "caption_delta", {"scene_id": scene_id, "text": event.text}
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
        guarded = guard_with_retry(
            self._client, messages, system, "".join(deltas).strip(), payloads
        )
        if guarded.warning is not None:
            yield Event("warning", guarded.warning)
        yield Event(
            "caption",
            {"scene_id": scene_id, "text": guarded.result.text, "guarded": True},
        )
        session.remember(
            Exchange(
                question=question,
                card_types=tuple(card.type for card in cards),
                caption=guarded.result.text,
            )
        )
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
