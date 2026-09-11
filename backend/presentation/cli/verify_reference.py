from __future__ import annotations

from backend.interfaces.cli.verify_reference import main


if __name__ == "__main__":
    from backend.interfaces.cli.verify_reference import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "main",
]
