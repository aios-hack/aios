from __future__ import annotations

from backend.interfaces.cli.final_campaign import (
    local_candidates,
    main,
)


if __name__ == "__main__":
    from backend.interfaces.cli.final_campaign import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "local_candidates",
    "main",
]
