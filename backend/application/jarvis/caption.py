from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from backend.application.jarvis.guard import GuardResult, guard_caption
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


def guard_with_retry(
    client: ChatClient,
    messages: Sequence[ChatMessage],
    system: str,
    caption: str,
    payloads: Sequence[Any],
) -> GuardedCaption:
    result = guard_caption(caption, payloads)
    if result.ok:
        return GuardedCaption(result=result, warning=None)
    retry = _retry(client, messages, system, result.dropped, caption)
    if retry is None:
        return GuardedCaption(result=result, warning=_warning(result.dropped))
    second = guard_caption(retry, payloads)
    if second.ok:
        return GuardedCaption(result=second, warning=None)
    return GuardedCaption(result=second, warning=_warning(second.dropped))
