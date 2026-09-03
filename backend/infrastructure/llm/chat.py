from __future__ import annotations

from typing import Iterator, Protocol, Sequence

from backend.infrastructure.llm.chat_events import ChatEvent, ChatMessage, ToolSpec


class ChatClient(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        system: str,
    ) -> Iterator[ChatEvent]: ...
