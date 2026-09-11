from __future__ import annotations

from backend.interfaces.cli.selfcheck import (
    CLAIMED_CANONICAL_FIELD,
    CLAIMED_CONTENT_FIELD,
    CLAIMED_NPV_FIELD,
    CLAIMED_NPV_FILE_NAME,
    CLI_MODULES,
    CheckLine,
    OPTIONAL_DEPENDENCIES,
    SubmissionCheckError,
    build_parser,
    check_submission,
    main,
)


if __name__ == "__main__":
    from backend.interfaces.cli.selfcheck import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "CLAIMED_CANONICAL_FIELD",
    "CLAIMED_CONTENT_FIELD",
    "CLAIMED_NPV_FIELD",
    "CLAIMED_NPV_FILE_NAME",
    "CLI_MODULES",
    "CheckLine",
    "OPTIONAL_DEPENDENCIES",
    "SubmissionCheckError",
    "build_parser",
    "check_submission",
    "main",
]
