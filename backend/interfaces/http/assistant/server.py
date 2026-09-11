from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from backend.contexts.assistant.infrastructure.artifacts import ArtifactError
from backend.contexts.assistant.infrastructure.knowledge import KnowledgeError
from backend.contexts.assistant.domain.session import SessionError
from backend.contexts.assistant.infrastructure.session_store import SessionDiskError
from backend.contexts.assistant.infrastructure.stt import SttError, SttUnavailable
from backend.contexts.assistant.infrastructure.tts import CONTENT_TYPE as AUDIO_CONTENT_TYPE
from backend.contexts.assistant.infrastructure.tts import TtsError, TtsUnavailable
from backend.contexts.assistant.application.assistant_service import (
    AUDIO_ROUTE,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEV_ORIGINS,
    MAX_AUDIO_BYTES,
    MAX_BODY_BYTES,
    JarvisService,
    console_context,
    query_context,
)
from backend.interfaces.http.kit.sse import (
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
                self.send_header(
                    "Access-Control-Allow-Headers", "Content-Type, X-Jarvis-Lang"
                )
                self.send_header("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS")

        def _json(self, status: int, body: Mapping[str, Any]) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

        def _raw(self, limit: int) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            if length > limit:
                raise ValueError(
                    f"request body of {length} bytes exceeds the {limit} "
                    "byte limit for this Jarvis route"
                )
            return self.rfile.read(length) if length else b""

        def _read(self) -> Mapping[str, Any]:
            raw = self._raw(MAX_BODY_BYTES) or b"{}"
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
            parts = urlsplit(self.path)
            route = parts.path.rstrip("/") or parts.path
            if route == "/api/jarvis/health":
                status, body = service.health()
                self._json(status, body)
                return
            if route == "/api/jarvis/sessions":
                self._json(200, {"sessions": service.session_rows()})
                return
            if route.startswith("/api/jarvis/sessions/"):
                self._session_events(route.rsplit("/", 1)[-1])
                return
            if route == "/api/jarvis/briefing":
                self._briefing(parse_qs(parts.query))
                return
            if route == "/api/jarvis/voices":
                self._voices(parse_qs(parts.query))
                return
            self._json(404, {"error": "not-found", "path": self.path})

        def do_DELETE(self) -> None:
            route = urlsplit(self.path).path.rstrip("/")
            if not route.startswith("/api/jarvis/sessions/"):
                self._json(404, {"error": "not-found", "path": self.path})
                return
            session_id = route.rsplit("/", 1)[-1]
            try:
                removed = service.remove_session(session_id)
            except SessionDiskError as error:
                self._json(400, {"error": "bad-request", "message": str(error)})
                return
            self._json(200, {"removed": removed, "id": session_id})

        def _session_events(self, session_id: str) -> None:
            try:
                events = service.session_events(session_id)
            except SessionDiskError as error:
                self._json(404, {"error": "no-session", "message": str(error)})
                return
            self._json(200, {"id": session_id, "events": events})

        def _briefing(self, params: Mapping[str, list[str]]) -> None:
            if not service.available:
                status, body = service.health()
                self._json(status, body)
                return
            values = params.get("session_id") or []
            session_id = values[0] if values else "briefing"
            console = query_context(params)
            try:
                events = service.briefing(session_id, console)
            except (ArtifactError, KnowledgeError) as error:
                self._json(503, {"error": "tool-failed", "message": str(error)})
                return
            except Exception as error:
                self._json(503, {"error": "upstream", "message": str(error)})
                return
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE)
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Transfer-Encoding", "chunked")
            self._cors()
            self.end_headers()
            writer = KeepAliveWriter(self.wfile)
            with writer:
                try:
                    for event in events:
                        writer.write(encode_event(event))
                except (BrokenPipeError, ConnectionResetError):
                    return
            try:
                self.wfile.write(final_chunk())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self) -> None:
            route = self.path.split("?", 1)[0].rstrip("/")
            if route == "/api/jarvis/cancel":
                self._cancel()
                return
            if route == "/api/jarvis/ask":
                self._ask()
                return
            if route == "/api/jarvis/speak":
                self._speak()
                return
            if route == AUDIO_ROUTE:
                self._transcribe()
                return
            self._json(404, {"error": "not-found", "path": self.path})

        def _voices(self, params: Mapping[str, list[str]]) -> None:
            values = params.get("lang") or []
            lang = values[0] if values else None
            try:
                listed = service.tts.voices(lang)
            except TtsUnavailable as error:
                self._json(
                    503, {"error": "tts-unavailable", "message": str(error)}
                )
                return
            except TtsError as error:
                self._json(400, {"error": "bad-request", "message": str(error)})
                return
            self._json(200, {"voices": [voice.as_dict() for voice in listed]})

        def _speak(self) -> None:
            try:
                payload = self._read()
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"error": "bad-request", "message": str(error)})
                return
            text = str(payload.get("text") or "")
            lang = str(payload.get("lang") or "ru")
            voice = payload.get("voice")
            try:
                chunks = list(
                    service.tts.stream(
                        text, lang, str(voice) if voice else None
                    )
                )
            except TtsUnavailable as error:
                self._json(
                    503, {"error": "tts-unavailable", "message": str(error)}
                )
                return
            except TtsError as error:
                self._json(400, {"error": "bad-request", "message": str(error)})
                return
            self.send_response(200)
            self.send_header("Content-Type", AUDIO_CONTENT_TYPE)
            self.send_header("Content-Length", str(sum(len(c) for c in chunks)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            for chunk in chunks:
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return

        def _transcribe(self) -> None:
            try:
                audio = self._raw(MAX_AUDIO_BYTES)
            except ValueError as error:
                self._json(413, {"error": "too-large", "message": str(error)})
                return
            lang = self.headers.get("X-Jarvis-Lang")
            try:
                transcript = service.stt.transcribe(
                    audio, lang, self.headers.get("Content-Type")
                )
            except SttUnavailable as error:
                self._json(
                    503, {"error": "stt-unavailable", "message": str(error)}
                )
                return
            except SttError as error:
                self._json(400, {"error": "bad-request", "message": str(error)})
                return
            self._json(200, transcript.as_dict())

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
    print(
        f"jarvis: http://{host}:{port} health={status} "
        f"{json.dumps(body['knowledge'])} docs={body['docs']} "
        f"sessions={body['sessions']}"
    )
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
