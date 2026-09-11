from __future__ import annotations

from backend.interfaces.cli.surrogate.check import (
    BASE_PHYSICS_GATE_NOTE,
    CASE_PHYSICS_GATE_NOTE,
    check,
    exit_code_for,
    main,
)


if __name__ == "__main__":
    from backend.interfaces.cli.surrogate.check import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "BASE_PHYSICS_GATE_NOTE",
    "CASE_PHYSICS_GATE_NOTE",
    "check",
    "exit_code_for",
    "main",
]
