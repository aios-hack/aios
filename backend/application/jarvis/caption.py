from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.application.jarvis.guard import (
    CODE_WARNING_CODE,
    CodeResult,
    GuardResult,
    guard_answer,
    guard_caption,
)
from backend.infrastructure.llm.chat import ChatClient
from backend.infrastructure.llm.chat_events import ChatMessage, Done, TextDelta

RETRY_PROMPT = (
    "The caption you produced contains numbers that no tool of this scene "
    "returned: {dropped}. Rewrite the caption in at most two sentences using "
    "only the values the tools returned, or with no numbers at all. Reply with "
    "the caption text only."
)
WARNING_CODE = "number-dropped"


@dataclass(frozen=True, slots=True)
class GuardedCaption:
    result: GuardResult
    warning: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class GuardedAnswer:
    text: str
    warnings: tuple[dict[str, Any], ...]


def _retry(
    client: ChatClient,
    messages: Sequence[ChatMessage],
    system: str,
    dropped: Sequence[str],
    previous: str,
) -> str | None:
    retry_messages = [
        *messages,
        ChatMessage(role="assistant", content=previous),
        ChatMessage(
            role="user", content=RETRY_PROMPT.format(dropped=", ".join(dropped))
        ),
    ]
    collected: list[str] = []
    try:
        for event in client.stream(retry_messages, (), system):
            if isinstance(event, TextDelta):
                collected.append(event.text)
            elif isinstance(event, Done):
                break
    except Exception:
        return None
    text = "".join(collected).strip()
    return text or None


def _warning(dropped: Sequence[str]) -> dict[str, Any]:
    return {
        "code": WARNING_CODE,
        "detail": (
            "numbers not backed by any tool result of this scene were removed: "
            f"{', '.join(dropped)}"
        ),
    }


def _code_warning(removed: Sequence[str]) -> dict[str, Any]:
    listed = "; ".join(item[:80] for item in removed)
    return {
        "code": CODE_WARNING_CODE,
        "detail": (
            "fenced code blocks that match no document hit and no guide control "
            f"were removed: {listed}"
        ),
    }


def guard_with_retry(
    client: ChatClient,
    messages: Sequence[ChatMessage],
    system: str,
    caption: str,
    payloads: Sequence[Any],
    evidence: Sequence[Any] = (),
) -> GuardedCaption:
    result = guard_caption(caption, payloads, evidence)
    if result.ok:
        return GuardedCaption(result=result, warning=None)
    retry = _retry(client, messages, system, result.dropped, caption)
    if retry is None:
        return GuardedCaption(result=result, warning=_warning(result.dropped))
    second = guard_caption(retry, payloads, evidence)
    if second.ok:
        return GuardedCaption(result=second, warning=None)
    return GuardedCaption(result=second, warning=_warning(second.dropped))


def guard_answer_text(
    answer: str,
    payloads: Sequence[Any],
    evidence: Sequence[Any] = (),
    code_sources: Sequence[str] = (),
) -> GuardedAnswer:
    result, code = guard_answer(answer, payloads, evidence, code_sources)
    warnings: list[dict[str, Any]] = []
    if not code.ok:
        warnings.append(_code_warning(code.removed))
    if not result.ok:
        warnings.append(_warning(result.dropped))
    return GuardedAnswer(text=result.text, warnings=tuple(warnings))


def doc_numbers(payloads: Sequence[Any]) -> list[float]:
    collected: list[float] = []
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        for hit in payload.get("hits") or ():
            if not isinstance(hit, Mapping):
                continue
            for value in hit.get("numbers") or ():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    collected.append(float(value))
    return collected


def code_sources(payloads: Sequence[Any]) -> list[str]:
    collected: list[str] = []
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        for hit in payload.get("hits") or ():
            if isinstance(hit, Mapping):
                for key in ("text", "snippet"):
                    value = hit.get(key)
                    if isinstance(value, str) and value:
                        collected.append(value)
        for control in payload.get("controls") or ():
            if not isinstance(control, Mapping):
                continue
            hotkey = control.get("hotkey")
            if isinstance(hotkey, str) and hotkey:
                collected.append(hotkey)
        for question in payload.get("questions") or ():
            if isinstance(question, str) and question:
                collected.append(question)
    return collected


__all__ = [
    "CodeResult",
    "GuardedAnswer",
    "GuardedCaption",
    "WARNING_CODE",
    "code_sources",
    "doc_numbers",
    "guard_answer_text",
    "guard_with_retry",
]
