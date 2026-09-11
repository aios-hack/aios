from __future__ import annotations

from backend.interfaces.cli.surrogate.audit import (
    main,
    ranking_metrics,
)


if __name__ == "__main__":
    from backend.interfaces.cli.surrogate.audit import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "main",
    "ranking_metrics",
]
