from __future__ import annotations

from backend.interfaces.cli.npv import (
    build_parser,
    main,
)


if __name__ == "__main__":
    from backend.interfaces.cli.npv import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "build_parser",
    "main",
]
