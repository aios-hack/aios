from __future__ import annotations

import io
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.knowledge import Knowledge
from backend.application.jarvis.orchestrator import Orchestrator
from backend.application.jarvis.session import SessionStore
from backend.infrastructure.llm.chat_events import ToolCall
from backend.infrastructure.llm.fake_chat import FakeChatClient
from backend.presentation.api import sse
from backend.presentation.api.jarvis_server import build_handler
from backend.presentation.api.service import JarvisService
from backend.presentation.api.sse import chunk, encode_event, error_event

CALL = ToolCall(id="c1", name="field_metrics", args={"step": 96})
CAPTION = "Фонд работает штатно."


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "frontend" / "public" / "data").is_dir():
            return parent
    raise RuntimeError("repository root with frontend/public/data was not found")


@pytest.fixture(scope="module")
def store() -> ArtifactStore:
    return ArtifactStore(repo_root() / "frontend" / "public" / "data")


@pytest.fixture(scope="module")
def knowledge() -> Knowledge:
    return Knowledge(repo_root() / "frontend" / "public" / "jarvis" / "knowledge")


def make_service(
    store: ArtifactStore, knowledge: Knowledge, with_key: bool
) -> JarvisService:
    if not with_key:
        return JarvisService(store=store, knowledge=knowledge, env={})
    client = FakeChatClient(rounds=[[CALL]], caption=CAPTION, model="fake/recorded")
    orchestrator = Orchestrator(
        client=client, store=store, knowledge=knowledge, sessions=SessionStore()
    )
    return JarvisService(
        store=store, knowledge=knowledge, env={}, orchestrator=orchestrator
    )


def run(service: JarvisService) -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(service))
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def live(store: ArtifactStore, knowledge: Knowledge) -> Iterator[str]:
    yield from run(make_service(store, knowledge, with_key=True))


@pytest.fixture()
def keyless(store: ArtifactStore, knowledge: Knowledge) -> Iterator[str]:
    yield from run(make_service(store, knowledge, with_key=False))


def post(url: str, body: dict[str, Any]) -> urllib.request.addinfourl:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(request, timeout=10)


def read_events(response: urllib.request.addinfourl) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in response:
        line = raw.decode("utf-8").strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :].strip()))
    return events


def test_health_reports_provider_and_knowledge(live: str) -> None:
    with urllib.request.urlopen(f"{live}/api/jarvis/health", timeout=5) as response:
        assert response.status == 200
        body = json.loads(response.read().decode("utf-8"))
    assert body["ok"] is True
    assert body["provider"] == "fake"
    assert body["model"] == "fake/recorded"
    assert body["data"] == "model-z-base-run"
    assert body["knowledge"]["terms"] >= 40
    assert body["knowledge"]["screens"] == 10


def test_health_without_key_is_503(keyless: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(f"{keyless}/api/jarvis/health", timeout=5)
    assert error.value.code == 503
    body = json.loads(error.value.read().decode("utf-8"))
    assert body["ok"] is False
    assert body["error"] == "no-api-key"
    assert body["knowledge"]["terms"] >= 40


def test_ask_without_key_is_503(keyless: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as error:
        post(
            f"{keyless}/api/jarvis/ask",
            {"session_id": "s", "question": "что с фондом"},
        )
    assert error.value.code == 503
    body = json.loads(error.value.read().decode("utf-8"))
    assert body["error"] == "no-api-key"


def test_ask_streams_the_contract_order(live: str) -> None:
    response = post(
        f"{live}/api/jarvis/ask",
        {
            "session_id": "s-live",
            "question": "что с фондом",
            "lang": "ru",
            "context": {"scenario": "base", "step": 96, "workspace": "overview", "view": "fund"},
        },
    )
    assert response.headers["Content-Type"].startswith("text/event-stream")
    events = read_events(response)
    kinds = [event["type"] for event in events]
    assert kinds[0] == "scene"
    assert kinds[-1] == "done"
    assert "card" in kinds
    assert "caption" in kinds
    assert "suggestions" in kinds
    card = next(event for event in events if event["type"] == "card")
    assert card["card"]["type"] == "metric"
    assert card["card"]["provenance"] == "model-z-base-run"
    caption = next(event for event in events if event["type"] == "caption")
    assert caption["text"] == CAPTION
    assert caption["guarded"] is True


def test_ask_rejects_an_empty_question(live: str) -> None:
    response = post(f"{live}/api/jarvis/ask", {"session_id": "s2", "question": ""})
    events = read_events(response)
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "bad-request"


def test_cancel_marks_the_session(live: str) -> None:
    response = post(f"{live}/api/jarvis/cancel", {"session_id": "s-cancel"})
    body = json.loads(response.read().decode("utf-8"))
    assert body["session_id"] == "s-cancel"


def test_unknown_route_is_404(live: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(f"{live}/api/jarvis/nope", timeout=5)
    assert error.value.code == 404


def test_cors_allows_the_dev_origin(live: str) -> None:
    request = urllib.request.Request(
        f"{live}/api/jarvis/health", headers={"Origin": "http://localhost:5199"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert (
            response.headers["Access-Control-Allow-Origin"]
            == "http://localhost:5199"
        )


def test_cors_is_absent_for_a_foreign_origin(live: str) -> None:
    request = urllib.request.Request(
        f"{live}/api/jarvis/health", headers={"Origin": "http://evil.example"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers.get("Access-Control-Allow-Origin") is None


def test_broken_json_body_is_400(live: str) -> None:
    request = urllib.request.Request(
        f"{live}/api/jarvis/ask",
        data=b"{not json",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=5)
    assert error.value.code == 400


def test_sse_encoding_is_one_json_line() -> None:
    encoded = encode_event({"type": "scene", "scene_id": "s-01"})
    assert encoded.startswith(b"data: ")
    assert encoded.endswith(b"\n\n")
    assert encoded.count(b"\n") == 2


def test_chunk_frames_the_payload() -> None:
    framed = chunk(b"abc")
    assert framed == b"3\r\nabc\r\n"


def test_error_event_carries_a_code() -> None:
    payload = json.loads(
        error_event("timeout", "took too long").decode("utf-8")[len("data: ") :]
    )
    assert payload == {
        "type": "error",
        "code": "timeout",
        "message": "took too long",
    }


class SlowFakeClient(FakeChatClient):
    def stream(self, messages: Any, tools: Any, system: str) -> Any:
        time.sleep(0.3)
        yield from super().stream(messages, tools, system)


@pytest.fixture()
def slow(store: ArtifactStore, knowledge: Knowledge) -> Iterator[str]:
    client = SlowFakeClient(rounds=[[CALL]], caption=CAPTION, model="fake/slow")
    orchestrator = Orchestrator(
        client=client, store=store, knowledge=knowledge, sessions=SessionStore()
    )
    service = JarvisService(
        store=store, knowledge=knowledge, env={}, orchestrator=orchestrator
    )
    yield from run(service)


def test_keepalive_comment_fills_a_silent_gap(
    slow: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sse, "KEEPALIVE_SECONDS", 0.05)
    response = post(
        f"{slow}/api/jarvis/ask",
        {"session_id": "s-keepalive", "question": "что с фондом"},
    )
    lines = [raw.decode("utf-8").rstrip("\r\n") for raw in response]
    assert any(line.startswith(":") for line in lines)
    assert any(line.startswith("data:") for line in lines)


def test_keepalive_writer_pulses_only_when_idle() -> None:
    sink = io.BytesIO()
    writer = sse.KeepAliveWriter(sink, interval=0.06)
    with writer:
        writer.write(b"data: {}\n\n")
        time.sleep(0.25)
    body = sink.getvalue()
    assert b"data: {}" in body
    assert sse.KEEPALIVE_COMMENT in body
    assert writer.failure is None


def test_keepalive_writer_stays_quiet_while_events_flow() -> None:
    sink = io.BytesIO()
    writer = sse.KeepAliveWriter(sink, interval=5.0)
    with writer:
        writer.write(b"data: {}\n\n")
        time.sleep(0.1)
    assert sse.KEEPALIVE_COMMENT not in sink.getvalue()
