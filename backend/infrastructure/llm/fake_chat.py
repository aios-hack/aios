from __future__ import annotations

from typing import Iterator, Sequence

from backend.infrastructure.llm.chat_events import (
    ChatEvent,
    ChatMessage,
    Done,
    TextDelta,
    ToolCall,
    ToolSpec,
)

TEXT_CHUNK = 24


class FakeChatClient:
    def __init__(
        self,
        rounds: Sequence[Sequence[ToolCall]],
        caption: str,
        model: str = "fake/recorded",
        chunk: int = TEXT_CHUNK,
    ) -> None:
        self._rounds = [tuple(calls) for calls in rounds]
        self._caption = caption
        self._model = model
        self._chunk = chunk
        self.calls: list[tuple[tuple[ChatMessage, ...], str]] = []

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def turns(self) -> int:
        return len(self.calls)

    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        system: str,
    ) -> Iterator[ChatEvent]:
        turn = len(self.calls)
        self.calls.append((tuple(messages), system))
        if turn < len(self._rounds):
            for call in self._rounds[turn]:
                yield call
            yield Done(stop="tool_calls")
            return
        for start in range(0, len(self._caption), self._chunk):
            yield TextDelta(text=self._caption[start : start + self._chunk])
        yield Done(stop="end_turn", usage={"input_tokens": 0, "output_tokens": 0})
