"""One command for the real search and OPM verification scenarios.

``full`` intentionally runs both expensive stages in order. It does not treat
a fast-model prediction as a verified result.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIOS optimisation workflow")
    parser.add_argument("mode", choices=("search", "verify", "full"))
    return parser


def main(argv: list[str] | None = None) -> int:
    mode = build_parser().parse_args(argv).mode
    if mode in {"search", "full"}:
        from aios_backend.application.optimization.search_run import main as search

        code = search()
        if code:
            return code
    if mode in {"verify", "full"}:
        from aios_backend.application.optimization.verification_run import main as verify

        return verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
