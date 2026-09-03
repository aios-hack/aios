from __future__ import annotations

import importlib
from typing import Any, Iterator, Sequence

from backend.infrastructure.llm.chat_events import (
    ChatEvent,
    ChatMessage,
    Done,
    TextDelta,
    ToolCall,
    ToolSpec,
)
from backend.infrastructure.llm.tools_format import (
    to_anthropic_messages,
    to_anthropic_tools,
)

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 1200
DEFAULT_TEMPERATURE = 0.2
SDK_MODULE = "anthropic"


def _sdk(api_key: str) -> Any:
    try:
        module = importlib.import_module(SDK_MODULE)
    except ImportError as error:
        raise RuntimeError(
            "the anthropic package is not installed: the Jarvis fallback "
            "provider needs it, while the primary path is OpenRouter over urllib"
        ) from error
    return module.Anthropic(api_key=api_key)


class AnthropicChatClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        sdk: Any | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set: the Jarvis fallback provider does "
                "not work without a key and the project ships no stub clients"
            )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = sdk if sdk is not None else _sdk(api_key)

    @property
    def provider(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        system: str,
    ) -> Iterator[ChatEvent]:
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "system": system,
            "messages": to_anthropic_messages(messages),
        }
        if tools:
            request["tools"] = to_anthropic_tools(tools)
        response = self._client.messages.create(**request)
        calls: list[ToolCall] = []
        for block in response.content:
            kind = getattr(block, "type", None)
            if kind == "text":
                yield TextDelta(text=block.text)
            elif kind == "tool_use":
                calls.append(
                    ToolCall(id=block.id, name=block.name, args=dict(block.input))
                )
        for call in calls:
            yield call
        usage_source = getattr(response, "usage", None)
        usage: dict[str, int] = {}
        if usage_source is not None:
            for key in ("input_tokens", "output_tokens"):
                value = getattr(usage_source, key, None)
                if isinstance(value, int):
                    usage[key] = value
        yield Done(stop=str(getattr(response, "stop_reason", "end_turn")), usage=usage)
