from __future__ import annotations

from backend.presentation.cli import web


def test_web_server_handles_requests_concurrently(monkeypatch, tmp_path) -> None:
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeThreadingHTTPServer:
        def __init__(self, address, handler) -> None:
            captured["address"] = address
            captured["handler"] = handler

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def serve_forever(self) -> None:
            captured["served"] = True

    monkeypatch.setattr(web.http.server, "ThreadingHTTPServer", FakeThreadingHTTPServer)

    assert web.main(["--dist", str(tmp_path), "--host", "127.0.0.1", "--port", "0"]) == 0
    assert captured["address"] == ("127.0.0.1", 0)
    assert captured["served"] is True
