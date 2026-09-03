from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from backend.application.jarvis.artifacts import ArtifactError
from backend.application.jarvis.knowledge import KnowledgeError
from backend.application.jarvis.session import SessionError
from backend.presentation.api.service import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEV_ORIGINS,
    MAX_BODY_BYTES,
    JarvisService,
    console_context,
)
from backend.presentation.api.sse import (
    CONTENT_TYPE,
    KeepAliveWriter,
    encode_event,
    error_event,
    final_chunk,
)


def build_handler(service: JarvisService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "AiosJarvis/1.0"

        def log_message(self, *args: Any) -> None:
            return

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin in DEV_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

        def _json(self, status: int, body: Mapping[str, Any]) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

        def _read(self) -> Mapping[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY_BYTES:
                raise ValueError(
                    f"request body of {length} bytes exceeds the {MAX_BODY_BYTES} "
                    "byte limit for a Jarvis request"
                )
            raw = self.rfile.read(length) if length else b"{}"
            loaded = json.loads(raw.decode("utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("the request body is not a JSON object")
            return loaded

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/api/jarvis/health":
                status, body = service.health()
                self._json(status, body)
                return
            self._json(404, {"error": "not-found", "path": self.path})

        def do_POST(self) -> None:
            route = self.path.split("?", 1)[0].rstrip("/")
            if route == "/api/jarvis/cancel":
                self._cancel()
                return
            if route == "/api/jarvis/ask":
                self._ask()
                return
            self._json(404, {"error": "not-found", "path": self.path})

        def _cancel(self) -> None:
            try:
                payload = self._read()
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"error": "bad-request", "message": str(error)})
                return
            session_id = str(payload.get("session_id") or "")
            cancelled = service.sessions.cancel(session_id)
            self._json(200, {"cancelled": cancelled, "session_id": session_id})

        def _ask(self) -> None:
            try:
                payload = self._read()
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"error": "bad-request", "message": str(error)})
                return
            if not service.available:
                status, body = service.health()
                self._json(status, body)
                return
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE)
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Transfer-Encoding", "chunked")
            self._cors()
            self.end_headers()
            self._stream(payload)

        def _stream(self, payload: Mapping[str, Any]) -> None:
            session_id = str(payload.get("session_id") or "")
            question = str(payload.get("question") or "")
            writer = KeepAliveWriter(self.wfile)
            with writer:
                try:
                    stream = service.orchestrator.ask(
                        session_id, question, console_context(payload)
                    )
                    for event in stream:
                        writer.write(encode_event(event.as_dict()))
                except SessionError as error:
                    self._emit_error(writer, "bad-request", str(error))
                except (ArtifactError, KnowledgeError) as error:
                    self._emit_error(writer, "tool-failed", str(error))
                except TimeoutError as error:
                    self._emit_error(writer, "timeout", str(error))
                except (BrokenPipeError, ConnectionResetError):
                    service.sessions.cancel(session_id)
                    return
                except Exception as error:
                    self._emit_error(writer, "upstream", str(error))
            try:
                self.wfile.write(final_chunk())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                service.sessions.cancel(session_id)

        def _emit_error(
            self, writer: KeepAliveWriter, code: str, message: str
        ) -> None:
            try:
                writer.write(error_event(code, message))
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    service: JarvisService | None = None,
) -> None:
    active = service if service is not None else JarvisService()
    httpd = ThreadingHTTPServer((host, port), build_handler(active))
    httpd.daemon_threads = True
    status, body = active.health()
    print(f"jarvis: http://{host}:{port} health={status} {json.dumps(body['knowledge'])}")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
