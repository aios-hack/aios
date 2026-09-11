from __future__ import annotations

from backend.contexts.showcase.application.champion_export import (
    CHAMPION,
    OUT,
    SCENARIO_ID,
    main,
)


if __name__ == "__main__":
    from backend.contexts.showcase.application.champion_export import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "CHAMPION",
    "OUT",
    "SCENARIO_ID",
    "main",
]
