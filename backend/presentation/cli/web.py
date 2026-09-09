from __future__ import annotations

import argparse
import functools
import http.server
import json
from urllib.parse import urlsplit
from backend.presentation.cli.web_runs import WebRuns
from pathlib import Path

from backend.presentation.api.proxy import forward, is_jarvis_path

DEFAULT_DIST = Path("/app/frontend/dist")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aios web",
        description="Отдача собранного веб-интерфейса frontend/dist.",
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
        if urlsplit(self.path).path == '/api/runs':
            self._json(200, {'runs': self.runs.list()})
        elif self.path.startswith('/api/'):
            self._json(404, {'error': 'Неизвестный запрос.'})
        else:
            super().do_GET()

    def do_POST(self):  # type: ignore[override]
        if is_jarvis_path(self.path):
            forward(self)
            return
        if urlsplit(self.path).path != '/api/runs':
            self._json(404, {'error': 'Неизвестный запрос.'})
            return
        origin = self.headers.get('Origin')
        if (origin and urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._json(403, {'error': 'Запускайте расчёт из интерфейса этого сервера.'})
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self._json(415, {'error': 'Ожидается документ с условиями.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100_000:
                raise ValueError('Некорректный размер условий.')
            payload = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Некорректное число.')))
            if not isinstance(payload, dict):
                raise ValueError('Ожидается документ с условиями.')
            self._json(202, self.runs.start(payload))
        except (ValueError, TypeError) as error:
            self._json(400, {'error': 'Проверьте условия: диапазоны значений, долю возврата воды и обе границы компенсации.'})
        except RuntimeError as error:
            self._json(409, {'error': str(error)})

    def send_head(self):  # type: ignore[override]
        path = self.translate_path(self.path)
        if not Path(path).exists() and "." not in Path(path).name:
            self.path = "/index.html"
        return super().send_head()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.dist.is_dir():
        raise SystemExit(
            f"собранный фронт не найден: {args.dist}. Стадия сборки фронта не "
            f"отработала: проверьте, что каталог frontend/ попал в контекст сборки "
            f"и npm run build прошёл без ошибок."
        )

    handler = functools.partial(SpaRequestHandler, directory=str(args.dist))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as server:
        SpaRequestHandler.runs.recover_interrupted()
        print(f"веб-интерфейс: http://{args.host}:{args.port} из {args.dist}")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
