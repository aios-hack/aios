from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterator, Sequence

from backend.infrastructure.llm.chat_events import (
    ChatEvent,
    ChatMessage,
    Done,
    TextDelta,
    ToolCall,
    ToolSpec,
)
from backend.infrastructure.llm.tools_format import to_openai_messages, to_openai_tools

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_MAX_TOKENS = 1200
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT = 60.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class UpstreamError(RuntimeError):
    pass


class _ToolCallBuffer:
    def __init__(self) -> None:
        self._slots: dict[int, dict[str, str]] = {}

    def absorb(self, deltas: Sequence[dict[str, Any]]) -> None:
        for delta in deltas:
            index = int(delta.get("index", 0))
            slot = self._slots.setdefault(index, {"id": "", "name": "", "args": ""})
            identifier = delta.get("id")
            if isinstance(identifier, str) and identifier:
                slot["id"] = identifier
            function = delta.get("function") or {}
            name = function.get("name")
            if isinstance(name, str) and name:
                slot["name"] = name
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                slot["args"] += arguments

    def drain(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for index in sorted(self._slots):
            slot = self._slots[index]
            if not slot["name"]:
                continue
            raw = slot["args"].strip() or "{}"
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as error:
                raise UpstreamError(
                    f"tool call arguments for {slot['name']} arrived as "
                    f"incomplete JSON and do not parse: {error}"
                ) from error
            if not isinstance(parsed, dict):
                raise UpstreamError(
                    f"tool call arguments for {slot['name']} are not a JSON object"
                )
            calls.append(
                ToolCall(
                    id=slot["id"] or f"call_{index}",
                    name=slot["name"],
                    args=parsed,
                )
            )
        self._slots.clear()
        return calls


def parse_sse_lines(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError as error:
            raise UpstreamError(
                f"the provider sent an SSE line that does not parse as JSON: {error}"
            ) from error


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set: the OpenRouter client does not "
                "work without a key and the project ships no stub clients"
            )
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout = timeout

    @property
    def provider(self) -> str:
        return "openrouter"

    @property
    def model(self) -> str:
        return self._model

    def _body(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        system: str,
    ) -> bytes:
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": True,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system},
                *to_openai_messages(messages),
            ],
        }
        if tools:
            payload["tools"] = to_openai_tools(tools)
            payload["tool_choice"] = "auto"
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _open(self, body: bytes) -> Any:
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-Title": "AIOS Jarvis",
            },
        )
        attempts = 0
        while True:
            attempts += 1
            try:
                return urllib.request.urlopen(request, timeout=self._timeout)
            except urllib.error.HTTPError as error:
                if error.code in RETRY_STATUSES and attempts == 1:
                    time.sleep(0.5)
                    continue
                detail = error.read().decode("utf-8", errors="replace")[:400]
                raise UpstreamError(
                    f"OpenRouter answered {error.code}: {detail or error.reason}"
                ) from error
            except urllib.error.URLError as error:
                if attempts == 1:
                    time.sleep(0.5)
                    continue
                raise UpstreamError(
                    f"OpenRouter is unreachable: {error.reason}"
                ) from error

    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        system: str,
    ) -> Iterator[ChatEvent]:
        response = self._open(self._body(messages, tools, system))
        buffer = _ToolCallBuffer()
        stop = "end_turn"
        usage: dict[str, int] = {}
        with response:
            lines = (line.decode("utf-8", errors="replace") for line in response)
            for chunk in parse_sse_lines(lines):
                reported = chunk.get("usage")
                if isinstance(reported, dict):
                    usage = {
                        key: int(value)
                        for key, value in reported.items()
                        if isinstance(value, int)
                    }
                error = chunk.get("error")
                if isinstance(error, dict):
                    raise UpstreamError(
                        "OpenRouter returned an error inside the stream: "
                        f"{error.get('message', 'no description given')}"
                    )
                for choice in chunk.get("choices", ()):
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield TextDelta(text=content)
                    calls = delta.get("tool_calls")
                    if isinstance(calls, list) and calls:
                        buffer.absorb(calls)
                    reason = choice.get("finish_reason")
                    if isinstance(reason, str) and reason:
                        stop = reason
        for call in buffer.drain():
            yield call
        yield Done(stop=stop, usage=usage)
