from __future__ import annotations

from typing import Any

import pytest

from backend.infrastructure.llm.anthropic_chat import AnthropicChatClient
from backend.infrastructure.llm.chat_events import ChatMessage, Done, TextDelta, ToolCall, ToolSpec
from backend.infrastructure.llm.fake_chat import FakeChatClient
from backend.infrastructure.llm.openrouter import OpenRouterClient
from backend.infrastructure.llm.provider import NoApiKeyError, build_client
from backend.infrastructure.llm.tools_format import (
    to_anthropic_messages,
    to_anthropic_tools,
    to_openai_messages,
    to_openai_tools,
)

TOOL = ToolSpec(
    name="rank_wells",
    description="рейтинг скважин",
    schema={"type": "object", "properties": {"by": {"type": "string"}}},
)


class _Block:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


class _Response:
    def __init__(self, content: list[Any], stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Block(input_tokens=5, output_tokens=3)


class _Messages:
    def __init__(self, response: _Response) -> None:
        self._response = response
        self.request: dict[str, Any] | None = None

    def create(self, **request: Any) -> _Response:
        self.request = request
        return self._response


class _Sdk:
    def __init__(self, response: _Response) -> None:
        self.messages = _Messages(response)


def test_openai_tool_format() -> None:
    formatted = to_openai_tools([TOOL])
    assert formatted[0]["type"] == "function"
    assert formatted[0]["function"]["name"] == "rank_wells"
    assert formatted[0]["function"]["parameters"]["type"] == "object"


def test_anthropic_tool_format() -> None:
    formatted = to_anthropic_tools([TOOL])
    assert formatted[0]["name"] == "rank_wells"
    assert formatted[0]["input_schema"]["type"] == "object"
    assert "parameters" not in formatted[0]


def test_openai_messages_carry_tool_results() -> None:
    messages = [
        ChatMessage(role="user", content="кто худший"),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=(ToolCall(id="c1", name="rank_wells", args={"by": "npv"}),),
        ),
        ChatMessage(role="tool", content="{}", tool_call_id="c1"),
    ]
    formatted = to_openai_messages(messages)
    assert formatted[1]["tool_calls"][0]["function"]["arguments"] == '{"by": "npv"}'
    assert formatted[2] == {"role": "tool", "tool_call_id": "c1", "content": "{}"}


def test_anthropic_messages_carry_tool_results() -> None:
    messages = [
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=(ToolCall(id="c1", name="rank_wells", args={"by": "npv"}),),
        ),
        ChatMessage(role="tool", content="{}", tool_call_id="c1"),
    ]
    formatted = to_anthropic_messages(messages)
    assert formatted[0]["content"][0]["type"] == "tool_use"
    assert formatted[1]["role"] == "user"
    assert formatted[1]["content"][0]["type"] == "tool_result"
    assert formatted[1]["content"][0]["tool_use_id"] == "c1"


def test_tool_result_without_id_refuses() -> None:
    with pytest.raises(ValueError):
        to_openai_messages([ChatMessage(role="tool", content="{}")])


def test_provider_prefers_openrouter() -> None:
    client = build_client({"OPENROUTER_API_KEY": "a", "ANTHROPIC_API_KEY": "b"})
    assert isinstance(client, OpenRouterClient)
    assert client.provider == "openrouter"


def test_provider_falls_back_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, Any] = {}

    def factory(api_key: str) -> Any:
        created["key"] = api_key
        return _Sdk(_Response([], "end_turn"))

    monkeypatch.setattr(
        "backend.infrastructure.llm.anthropic_chat._sdk", factory
    )
    client = build_client({"ANTHROPIC_API_KEY": "b"})
    assert isinstance(client, AnthropicChatClient)
    assert client.provider == "anthropic"
    assert created["key"] == "b"


def test_provider_strips_vendor_prefix_for_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.infrastructure.llm.anthropic_chat._sdk",
        lambda api_key: _Sdk(_Response([], "end_turn")),
    )
    client = build_client(
        {"ANTHROPIC_API_KEY": "b", "JARVIS_MODEL": "anthropic/claude-sonnet-4.5"}
    )
    assert client.model == "claude-sonnet-4.5"


def test_provider_without_keys_raises() -> None:
    with pytest.raises(NoApiKeyError) as error:
        build_client({})
    assert "OPENROUTER_API_KEY" in str(error.value)


def test_unknown_provider_refuses() -> None:
    with pytest.raises(RuntimeError):
        build_client({"JARVIS_PROVIDER": "openai", "OPENROUTER_API_KEY": "a"})


def test_anthropic_stream_maps_blocks() -> None:
    response = _Response(
        [
            _Block(type="text", text="Скважина 13 работает."),
            _Block(type="tool_use", id="c1", name="rank_wells", input={"by": "npv"}),
        ],
        "tool_use",
    )
    client = AnthropicChatClient(api_key="k", sdk=_Sdk(response))
    events = list(client.stream([ChatMessage(role="user", content="?")], [TOOL], "s"))
    assert isinstance(events[0], TextDelta)
    assert isinstance(events[1], ToolCall)
    assert events[1].args == {"by": "npv"}
    assert isinstance(events[2], Done)
    assert events[2].usage == {"input_tokens": 5, "output_tokens": 3}


def test_fake_client_replays_rounds_then_caption() -> None:
    client = FakeChatClient(
        rounds=[[ToolCall(id="c1", name="rank_wells", args={"by": "npv"})]],
        caption="Итог по фонду.",
    )
    first = list(client.stream([], [TOOL], "s"))
    assert isinstance(first[0], ToolCall)
    second = list(client.stream([], [TOOL], "s"))
    text = "".join(e.text for e in second if isinstance(e, TextDelta))
    assert text == "Итог по фонду."
    assert client.turns == 2
