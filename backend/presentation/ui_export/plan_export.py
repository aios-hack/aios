from __future__ import annotations

from backend.contexts.showcase.application.plan_export import (
    CMAES,
    CONSTRAINTS,
    FINAL_CAP,
    LAMBDA,
    OUT,
    RESPONSE,
    SCENARIO_ID,
    main,
)


if __name__ == "__main__":
    from backend.contexts.showcase.application.plan_export import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "CMAES",
    "CONSTRAINTS",
    "FINAL_CAP",
    "LAMBDA",
    "OUT",
    "RESPONSE",
    "SCENARIO_ID",
    "main",
]
