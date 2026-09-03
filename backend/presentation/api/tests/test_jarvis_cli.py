from __future__ import annotations

import functools
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.presentation.api import proxy
from backend.presentation.cli import jarvis as cli
from backend.presentation.cli.web import SpaRequestHandler

ENTRYPOINT_COMMAND = "jarvis) cmd_jarvis"


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "docker" / "entrypoint.sh").is_file():
            return parent
    raise RuntimeError("repository root with docker/entrypoint.sh was not found")


def test_parser_defaults_to_the_service_port() -> None:
    args = cli.build_parser().parse_args([])
    assert args.port == 8010
    assert args.check is False


def test_parser_reads_host_and_port_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(cli.HOST_ENV_VAR, "127.0.0.1")
    monkeypatch.setenv(cli.PORT_ENV_VAR, "9010")
    args = cli.build_parser().parse_args([])
    assert (args.host, args.port) == ("127.0.0.1", 9010)


def test_check_without_a_key_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = cli.main(["--check"])
    assert code == 1
    assert "health=503" in capsys.readouterr().out


def test_entrypoint_exposes_the_jarvis_command() -> None:
    script = (repo_root() / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert ENTRYPOINT_COMMAND in script
    assert "backend.presentation.cli.jarvis" in script


def test_compose_declares_the_jarvis_service() -> None:
    compose = (repo_root() / "docker-compose.yml").read_text(encoding="utf-8")
    assert "\n  jarvis:\n" in compose
    assert 'command: ["jarvis"]' in compose
    assert "OPENROUTER_API_KEY" in compose
    assert "AIOS_JARVIS_PORT:-8010" in compose


def test_readme_documents_the_service() -> None:
    readme = (repo_root() / "README.md").read_text(encoding="utf-8")
    assert "## Джарвис" in readme
    assert "backend.presentation.cli.jarvis" in readme
    assert "no-api-key" in readme


def test_proxy_recognises_only_the_jarvis_prefix() -> None:
    assert proxy.is_jarvis_path("/api/jarvis/health")
    assert proxy.is_jarvis_path("/api/jarvis/ask?x=1")
    assert not proxy.is_jarvis_path("/data/wells.json")
    assert not proxy.is_jarvis_path("/api/jarvis")


def test_proxy_base_follows_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(proxy.JARVIS_UPSTREAM_ENV_VAR, "http://elsewhere:9010/")
    assert proxy.upstream_base() == "http://elsewhere:9010"


class UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        payload = json.dumps({"ok": True, "path": self.path}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def spawn(handler: type[BaseHTTPRequestHandler], directory: Path | None = None) -> Any:
    if directory is None:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    else:
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            functools.partial(handler, directory=str(directory)),
        )
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.fixture()
def web_with_upstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[str]:
    upstream = spawn(UpstreamHandler)
    monkeypatch.setenv(
        proxy.JARVIS_UPSTREAM_ENV_VAR,
        f"http://127.0.0.1:{upstream.server_address[1]}",
    )
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    web = spawn(SpaRequestHandler, directory=tmp_path)
    try:
        yield f"http://127.0.0.1:{web.server_address[1]}"
    finally:
        web.shutdown()
        web.server_close()
        upstream.shutdown()
        upstream.server_close()


def test_web_forwards_the_jarvis_prefix(web_with_upstream: str) -> None:
    with urllib.request.urlopen(
        f"{web_with_upstream}/api/jarvis/health", timeout=5
    ) as response:
        body = json.loads(response.read().decode("utf-8"))
    assert body == {"ok": True, "path": "/api/jarvis/health"}


def test_web_still_serves_static_files(web_with_upstream: str) -> None:
    with urllib.request.urlopen(f"{web_with_upstream}/index.html", timeout=5) as page:
        assert page.read().decode("utf-8").startswith("<!doctype html>")
