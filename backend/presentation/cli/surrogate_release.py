from __future__ import annotations

from backend.interfaces.cli.surrogate.release import (
    build_parser,
    main,
    package,
    render_verdict,
    verify,
)


if __name__ == "__main__":
    from backend.interfaces.cli.surrogate.release import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "build_parser",
    "main",
    "package",
    "render_verdict",
    "verify",
]
