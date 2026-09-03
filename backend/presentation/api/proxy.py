from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import Any

JARVIS_UPSTREAM_ENV_VAR = "AIOS_JARVIS_UPSTREAM"
DEFAULT_UPSTREAM = "http://jarvis:8010"
PREFIX = "/api/jarvis/"
STREAM_CHUNK = 1024
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


def upstream_base() -> str:
    return os.environ.get(JARVIS_UPSTREAM_ENV_VAR, DEFAULT_UPSTREAM).rstrip("/")


def is_jarvis_path(path: str) -> bool:
    return path.split("?", 1)[0].startswith(PREFIX)


def forward(handler: Any) -> None:
    target = f"{upstream_base()}{handler.path}"
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length) if length else None
    request = urllib.request.Request(
        target,
        data=body,
        method=handler.command,
        headers={
            "Content-Type": handler.headers.get("Content-Type", "application/json"),
            "Accept": handler.headers.get("Accept", "*/*"),
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=90)
    except urllib.error.HTTPError as error:
        _relay(handler, error.code, error.headers, error)
        return
    except urllib.error.URLError as error:
        handler.send_response(502)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        payload = (
            '{"type":"error","code":"upstream","message":'
            f'"jarvis service at {upstream_base()} is unreachable: {error.reason}"}}'
        ).encode("utf-8")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
        return
    with response:
        _relay(handler, response.status, response.headers, response)


def _relay(handler: Any, status: int, headers: Any, stream: Any) -> None:
    handler.send_response(status)
    for name, value in headers.items():
        if name.lower() in HOP_BY_HOP or name.lower() == "content-length":
            continue
        handler.send_header(name, value)
    handler.send_header("Transfer-Encoding", "chunked")
    handler.end_headers()
    while True:
        block = stream.read(STREAM_CHUNK)
        if not block:
            break
        handler.wfile.write(f"{len(block):X}\r\n".encode("ascii") + block + b"\r\n")
        handler.wfile.flush()
    handler.wfile.write(b"0\r\n\r\n")
    handler.wfile.flush()
