from __future__ import annotations

import sys
from typing import Callable, Sequence, TextIO

from backend.interfaces.logging_setup import configure
from backend.shared.errors import (
    AiosError,
    ConfigurationError,
    ConflictError,
    InfrastructureError,
    NotFoundError,
    UnavailableError,
    ValidationError,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_VALIDATION = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_CONFIGURATION = 5
EXIT_INFRASTRUCTURE = 6

_EXIT_CODES: tuple[tuple[type[AiosError], int], ...] = (
    (ValidationError, EXIT_VALIDATION),
    (NotFoundError, EXIT_NOT_FOUND),
    (ConflictError, EXIT_CONFLICT),
    (ConfigurationError, EXIT_CONFIGURATION),
    (UnavailableError, EXIT_CONFIGURATION),
    (InfrastructureError, EXIT_INFRASTRUCTURE),
)


def exit_code_for(error: AiosError) -> int:
    for kind, code in _EXIT_CODES:
        if isinstance(error, kind):
            return code
    return EXIT_ERROR


def run(main: Callable[..., int | None], argv: Sequence[str] | None = None, stderr: TextIO | None = None) -> int:
    stream = sys.stderr if stderr is None else stderr
    configure()
    try:
        result = main() if argv is None else main(argv)
    except AiosError as error:
        print(f"error[{error.code}]: {error.message}", file=stream)
        return exit_code_for(error)
    if result is None:
        return EXIT_OK
    return int(result)


def main_guard(main: Callable[..., int | None]) -> None:
    raise SystemExit(run(main))


__all__ = [
    "EXIT_CONFIGURATION",
    "EXIT_CONFLICT",
    "EXIT_ERROR",
    "EXIT_INFRASTRUCTURE",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_VALIDATION",
    "exit_code_for",
    "main_guard",
    "run",
]
