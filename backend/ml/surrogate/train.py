from __future__ import annotations

from backend.contexts.surrogate.application.train import (
    Split,
    TrainingCommandError,
    evaluate,
    main,
    money_rub_per_unit,
    split_samples,
)


if __name__ == "__main__":
    from backend.contexts.surrogate.application.train import main as _main

    raise SystemExit(_main())


__all__ = [
    "Split",
    "TrainingCommandError",
    "evaluate",
    "main",
    "money_rub_per_unit",
    "split_samples",
]
