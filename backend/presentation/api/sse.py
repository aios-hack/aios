from __future__ import annotations

import json
import threading
import time
from typing import Any, BinaryIO, Callable, Mapping

KEEPALIVE_SECONDS = 15.0
KEEPALIVE_COMMENT = b": keep-alive\n\n"
CONTENT_TYPE = "text/event-stream; charset=utf-8"


def encode_event(payload: Mapping[str, Any]) -> bytes:
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return f"data: {line}\n\n".encode("utf-8")


def chunk(body: bytes) -> bytes:
    return f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n"


def final_chunk() -> bytes:
    return b"0\r\n\r\n"


def error_event(code: str, message: str) -> bytes:
    return encode_event({"type": "error", "code": code, "message": message})


class KeepAliveWriter:
    def __init__(
        self,
        stream: BinaryIO,
        interval: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stream = stream
        self._interval = interval if interval is not None else KEEPALIVE_SECONDS
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last = clock()
        self._thread: threading.Thread | None = None
        self.failure: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._pulse, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=self._interval)

    def write(self, body: bytes) -> None:
        with self._lock:
            self._emit(body)

    def _emit(self, body: bytes) -> None:
        self._stream.write(chunk(body))
        self._stream.flush()
        self._last = self._clock()

    def _pulse(self) -> None:
        while not self._stop.wait(self._interval / 3.0):
            with self._lock:
                if self._clock() - self._last < self._interval:
                    continue
                try:
                    self._stream.write(chunk(KEEPALIVE_COMMENT))
                    self._stream.flush()
                    self._last = self._clock()
                except (BrokenPipeError, ConnectionResetError, ValueError) as error:
                    self.failure = error
                    return

    def __enter__(self) -> "KeepAliveWriter":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
