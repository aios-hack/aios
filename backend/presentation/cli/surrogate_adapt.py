from __future__ import annotations

from backend.interfaces.cli.surrogate.adapt import (
    combine,
    ensure_disjoint_splits,
    errors,
    main,
    sample_scenarios,
    scaled,
)


if __name__ == "__main__":
    from backend.interfaces.cli.surrogate.adapt import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "combine",
    "ensure_disjoint_splits",
    "errors",
    "main",
    "sample_scenarios",
    "scaled",
]
