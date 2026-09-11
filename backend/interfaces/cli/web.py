from __future__ import annotations

import argparse
import functools
import http.server
import json
from urllib.parse import urlsplit
from backend.contexts.runs.application.web_runs import WebRuns
from pathlib import Path

from backend.interfaces.http.console.proxy import forward, is_jarvis_path
from backend.interfaces.cli.runner import run as run_cli
from backend.interfaces.http.kit.errors import to_response
from backend.contexts.runs.domain.errors import RunRequestError
from backend.shared.errors import AiosError
from backend.shared.i18n.catalog import translate

DEFAULT_DIST = Path("/app/frontend/dist")
MAX_BODY_BYTES = 100_000
UNKNOWN_ROUTE_KEY = "http.error.unknown_route"
COMPARISON_ABSENT_KEY = "runs.comparison.absent"
FOREIGN_ORIGIN_KEY = "runs.request.foreign_origin"
BODY_SIZE_KEY = "runs.request.body_size"
BODY_SHAPE_KEY = "runs.request.body_shape"
BODY_NUMBER_KEY = "runs.request.body_number"
BODY_SIZE_REJECTED = translate(BODY_SIZE_KEY)
BODY_SHAPE_REJECTED = translate(BODY_SHAPE_KEY)
BODY_NUMBER_REJECTED = translate(BODY_NUMBER_KEY)


def _reject_constant(value: str) -> float:
    raise RunRequestError(BODY_NUMBER_REJECTED, message_key=BODY_NUMBER_KEY)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aios web",
        description="Serve the built web interface from frontend/dist.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    return parser


class SpaRequestHandler(http.server.SimpleHTTPRequestHandler):
    runs = WebRuns(Path('out/web-runs'))

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # type: ignore[override]
        if is_jarvis_path(self.path):
            forward(self)
            return
        route = urlsplit(self.path).path
        if route == '/api/runs':
            self._json(200, {'runs': self.runs.list()})
        elif route.startswith('/api/runs/') and route.endswith('/comparison'):
            run_id = route[len('/api/runs/'):-len('/comparison')]
            document = self.runs.comparison(run_id)
            if document is None:
                self._json(
                    404,
                    {
                        'error': COMPARISON_ABSENT_KEY,
                        'message': translate(COMPARISON_ABSENT_KEY),
                    },
                )
            else:
                self._json(200, document)
        elif self.path.startswith('/api/'):
            self._json(
                404,
                {'error': UNKNOWN_ROUTE_KEY, 'message': translate(UNKNOWN_ROUTE_KEY)},
            )
        else:
            super().do_GET()

    def do_DELETE(self):  # type: ignore[override]
        if is_jarvis_path(self.path):
            forward(self)
            return
        self._json(
                404,
                {'error': UNKNOWN_ROUTE_KEY, 'message': translate(UNKNOWN_ROUTE_KEY)},
            )

    def do_POST(self):  # type: ignore[override]
        if is_jarvis_path(self.path):
            forward(self)
            return
        if urlsplit(self.path).path != '/api/runs':
            self._json(
                404,
                {'error': UNKNOWN_ROUTE_KEY, 'message': translate(UNKNOWN_ROUTE_KEY)},
            )
            return
        origin = self.headers.get('Origin')
        if (origin and urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._json(
                403,
                {
                    'error': FOREIGN_ORIGIN_KEY,
                    'message': translate(FOREIGN_ORIGIN_KEY),
                },
            )
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self._json(
                415,
                {'error': BODY_SHAPE_KEY, 'message': BODY_SHAPE_REJECTED},
            )
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY_BYTES:
                raise RunRequestError(BODY_SIZE_REJECTED, message_key=BODY_SIZE_KEY)
            payload = json.loads(
                self.rfile.read(length),
                parse_constant=_reject_constant,
            )
            if not isinstance(payload, dict):
                raise RunRequestError(BODY_SHAPE_REJECTED, message_key=BODY_SHAPE_KEY)
            self._json(202, self.runs.start(payload))
        except AiosError as error:
            status, body = to_response(error)
            self._json(status, body)
        except (ValueError, TypeError) as error:
            status, body = to_response(RunRequestError(str(error)))
            self._json(status, body)

    def send_head(self):  # type: ignore[override]
        path = self.translate_path(self.path)
        if not Path(path).exists() and "." not in Path(path).name:
            self.path = "/index.html"
        return super().send_head()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.dist.is_dir():
        raise SystemExit(
            f"built frontend not found: {args.dist}. The frontend build stage did not "
            f"run: check that the frontend/ directory reached the build context "
            f"and that npm run build finished without errors."
        )

    handler = functools.partial(SpaRequestHandler, directory=str(args.dist))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as server:
        SpaRequestHandler.runs.recover_interrupted()
        print(f"web interface: http://{args.host}:{args.port} from {args.dist}")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
