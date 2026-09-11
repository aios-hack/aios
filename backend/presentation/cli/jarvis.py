from __future__ import annotations

from backend.interfaces.cli.jarvis import (
    DATA_ENV_VAR,
    HOST_ENV_VAR,
    KNOWLEDGE_ENV_VAR,
    PORT_ENV_VAR,
    build_parser,
    main,
    record,
)


if __name__ == "__main__":
    from backend.interfaces.cli.jarvis import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "DATA_ENV_VAR",
    "HOST_ENV_VAR",
    "KNOWLEDGE_ENV_VAR",
    "PORT_ENV_VAR",
    "build_parser",
    "main",
    "record",
]
