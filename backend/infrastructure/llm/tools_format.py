from __future__ import annotations

import json
from typing import Any, Sequence

from backend.infrastructure.llm.chat_events import ChatMessage, ToolSpec


def to_openai_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.schema),
            },
        }
        for tool in tools
    ]


def to_anthropic_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": dict(tool.schema),
        }
        for tool in tools
    ]


def to_openai_messages(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            if message.tool_call_id is None:
                raise ValueError(
                    "a tool result carries no tool_call_id: the provider cannot "
                    "match it to the call that produced it"
                )
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content or "",
                }
            )
            continue
        entry: dict[str, Any] = {"role": message.role}
        entry["content"] = message.content
        if message.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": _dumps(call.args),
                    },
                }
                for call in message.tool_calls
            ]
        result.append(entry)
    return result


def to_anthropic_messages(
    messages: Sequence[ChatMessage],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            if message.tool_call_id is None:
                raise ValueError(
                    "a tool result carries no tool_call_id: the provider cannot "
                    "match it to the call that produced it"
                )
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content or "",
                        }
                    ],
                }
            )
            continue
        blocks: list[dict[str, Any]] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        for call in message.tool_calls:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": dict(call.args),
                }
            )
        result.append({"role": message.role, "content": blocks})
    return result


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
