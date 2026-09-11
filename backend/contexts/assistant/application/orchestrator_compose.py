from __future__ import annotations

from typing import Any, Iterator, Sequence

from backend.contexts.assistant.application.answer import split_answer
from backend.contexts.assistant.application.caption import (
    code_sources,
    doc_numbers,
    guard_answer_text,
    guard_with_retry,
)
from backend.contexts.assistant.application.orchestrator_events import Event
from backend.contexts.assistant.application.suggestions import build_suggestions
from backend.contexts.assistant.application.tools import error_card, run_tool
from backend.contexts.assistant.application.tools.context import (
    Card,
    ConsoleContext,
    ToolContext,
    ToolFailure,
)
from backend.contexts.assistant.application.tools.registry import ToolInputError
from backend.contexts.assistant.domain.session import Exchange, Session, summary_request
from backend.contexts.assistant.infrastructure.artifacts import ArtifactStore, RunError
from backend.contexts.assistant.infrastructure.llm.chat import ChatClient
from backend.contexts.assistant.infrastructure.llm.chat_events import (
    ChatMessage,
    Done,
    TextDelta,
    ToolCall,
)
from backend.contexts.assistant.infrastructure.session_store import SessionDisk


def live_status(context: ToolContext) -> dict[str, Any] | None:
    try:
        card = run_tool("system_status", context, {})
    except Exception:
        return None
    return dict(card.payload)


def evidence_of(context: ToolContext) -> tuple[Any, ...]:
    try:
        record = context.run_store().read()
    except (ToolFailure, RunError):
        return ()
    return record.documents()


def call_tool(context: ToolContext, call: ToolCall) -> tuple[Card, Any]:
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


def compress_session(
    client: ChatClient, disk: SessionDisk | None, session: Session, system: str
) -> None:
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
        for event in client.stream(
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
    if disk is not None and session.summary_text:
        try:
            disk.set_summary(session.session_id, session.summary_text)
        except Exception:
            return


def compose(
    client: ChatClient,
    store: ArtifactStore,
    disk: SessionDisk | None,
    context: ToolContext,
    console: ConsoleContext,
    session: Session,
    scene_id: str,
    question: str,
    messages: list[ChatMessage],
    system: str,
    cards: Sequence[Card],
    deltas: Sequence[str],
    rounds: int,
    elapsed_ms: int,
) -> Iterator[Event]:
    yield Event("status", {"state": "composing"})
    payloads = [dict(card.payload) for card in cards]
    evidence = (*evidence_of(context), *doc_numbers(payloads))
    split = split_answer("".join(deltas))
    guarded = guard_with_retry(
        client, messages, system, split.caption, payloads, evidence
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
    compress_session(client, disk, session, system)
    yield Event(
        "suggestions",
        {
            "items": build_suggestions(
                console,
                store,
                card_types=tuple(card.type for card in cards),
                history=session.questions(),
            )
        },
    )
    yield Event(
        "done",
        {
            "scene_id": scene_id,
            "tool_rounds": rounds,
            "elapsed_ms": elapsed_ms,
        },
    )
