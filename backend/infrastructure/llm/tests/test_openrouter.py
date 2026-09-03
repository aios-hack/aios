from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

import pytest

from backend.infrastructure.llm.chat_events import ChatMessage, Done, TextDelta, ToolCall, ToolSpec
from backend.infrastructure.llm.openrouter import (
    OpenRouterClient,
    UpstreamError,
    parse_sse_lines,
)

TOOL = ToolSpec(
    name="well_snapshot",
    description="снимок скважины",
    schema={
        "type": "object",
        "properties": {"well": {"type": "string"}, "step": {"type": "integer"}},
        "required": ["well"],
    },
)

RECORDED_TOOL_STREAM: tuple[str, ...] = (
    ': OPENROUTER PROCESSING',
    'data: {"id":"gen-1","choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}',
    'data: {"id":"gen-1","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_a","type":"function","function":{"name":"well_snapshot","arguments":""}}]}}]}',
    'data: {"id":"gen-1","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"we"}}]}}]}',
    'data: {"id":"gen-1","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"ll\\": \\"13"}}]}}]}',
    'data: {"id":"gen-1","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\", \\"step\\": 96}"}}]}}]}',
    'data: {"id":"gen-1","choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"id":"call_b","type":"function","function":{"name":"field_metrics","arguments":"{\\"step\\":"}}]}}]}',
    'data: {"id":"gen-1","choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"function":{"arguments":" 96}"}}]}}]}',
    'data: {"id":"gen-1","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":11,"completion_tokens":7}}',
    "data: [DONE]",
)

RECORDED_TEXT_STREAM: tuple[str, ...] = (
    'data: {"id":"gen-2","choices":[{"index":0,"delta":{"content":"Скважина 13 "}}]}',
    'data: {"id":"gen-2","choices":[{"index":0,"delta":{"content":"работает."}}]}',
    'data: {"id":"gen-2","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
    "data: [DONE]",
)


class _Recorder:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.status: int = 200
        self.bodies: list[dict[str, Any]] = []
        self.authorization: str | None = None


def _handler(recorder: _Recorder) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            recorder.bodies.append(json.loads(raw.decode("utf-8")))
            recorder.authorization = self.headers.get("Authorization")
            if recorder.status != 200:
                payload = json.dumps({"error": {"message": "перегрузка"}}).encode()
                self.send_response(recorder.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            body = ("\n\n".join(recorder.lines) + "\n\n").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@pytest.fixture()
def server() -> Iterator[tuple[str, _Recorder]]:
    recorder = _Recorder()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(recorder))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    try:
        yield f"http://{host}:{port}", recorder
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_split_tool_arguments_are_reassembled(
    server: tuple[str, _Recorder],
) -> None:
    base_url, recorder = server
    recorder.lines = list(RECORDED_TOOL_STREAM)
    client = OpenRouterClient(api_key="k", base_url=base_url, model="test/model")
    events = list(
        client.stream([ChatMessage(role="user", content="что со скважиной 13")], [TOOL], "система")
    )
    calls = [event for event in events if isinstance(event, ToolCall)]
    assert [call.name for call in calls] == ["well_snapshot", "field_metrics"]
    assert calls[0].args == {"well": "13", "step": 96}
    assert calls[0].id == "call_a"
    assert calls[1].args == {"step": 96}
    done = events[-1]
    assert isinstance(done, Done)
    assert done.stop == "tool_calls"
    assert done.usage == {"prompt_tokens": 11, "completion_tokens": 7}


def test_text_stream_yields_deltas(server: tuple[str, _Recorder]) -> None:
    base_url, recorder = server
    recorder.lines = list(RECORDED_TEXT_STREAM)
    client = OpenRouterClient(api_key="k", base_url=base_url)
    events = list(client.stream([ChatMessage(role="user", content="?")], [], "система"))
    deltas = [event.text for event in events if isinstance(event, TextDelta)]
    assert deltas == ["Скважина 13 ", "работает."]
    assert isinstance(events[-1], Done)
    assert events[-1].stop == "stop"


def test_request_body_carries_tools_and_stream(server: tuple[str, _Recorder]) -> None:
    base_url, recorder = server
    recorder.lines = list(RECORDED_TEXT_STREAM)
    client = OpenRouterClient(api_key="secret", base_url=base_url, model="m/x")
    list(client.stream([ChatMessage(role="user", content="?")], [TOOL], "система"))
    body = recorder.bodies[-1]
    assert body["stream"] is True
    assert body["model"] == "m/x"
    assert body["messages"][0] == {"role": "system", "content": "система"}
    assert body["tools"][0]["function"]["name"] == "well_snapshot"
    assert body["tools"][0]["function"]["parameters"]["required"] == ["well"]
    assert recorder.authorization == "Bearer secret"


def test_retry_once_then_report_upstream(server: tuple[str, _Recorder]) -> None:
    base_url, recorder = server
    recorder.status = 429
    recorder.lines = list(RECORDED_TEXT_STREAM)
    client = OpenRouterClient(api_key="k", base_url=base_url)
    with pytest.raises(UpstreamError) as error:
        list(client.stream([ChatMessage(role="user", content="?")], [], "s"))
    assert "429" in str(error.value)
    assert len(recorder.bodies) == 2


def test_broken_json_arguments_reported(server: tuple[str, _Recorder]) -> None:
    base_url, recorder = server
    recorder.lines = [
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"c","type":"function","function":{"name":"well_snapshot","arguments":"{\\"well\\":"}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    client = OpenRouterClient(api_key="k", base_url=base_url)
    with pytest.raises(UpstreamError) as error:
        list(client.stream([ChatMessage(role="user", content="?")], [TOOL], "s"))
    assert "incomplete JSON" in str(error.value)


def test_sse_parser_skips_comments_and_stops_on_done() -> None:
    lines = iter([": keep-alive", "", 'data: {"a": 1}', "data: [DONE]", 'data: {"b": 2}'])
    assert list(parse_sse_lines(lines)) == [{"a": 1}]


def test_sse_parser_rejects_broken_line() -> None:
    with pytest.raises(UpstreamError):
        list(parse_sse_lines(iter(["data: {не json}"])))


def test_missing_key_refuses() -> None:
    with pytest.raises(RuntimeError) as error:
        OpenRouterClient(api_key="")
    assert "OPENROUTER_API_KEY" in str(error.value)
