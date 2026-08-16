from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path

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
    with socketserver.TCPServer((args.host, args.port), handler) as server:
        print(f"веб-интерфейс: http://{args.host}:{args.port} из {args.dist}")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
