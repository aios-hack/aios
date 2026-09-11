from __future__ import annotations

from backend.contexts.surrogate.application.train.cli import _parser, main
from backend.contexts.surrogate.application.train.evaluation import (
    evaluate,
    money_rub_per_unit,
)
from backend.contexts.surrogate.application.train.samples import (
    Split,
    _examples,
    split_samples,
)
from backend.contexts.surrogate.domain.errors import TrainingCommandError


__all__ = [
    "Split",
    "TrainingCommandError",
    "evaluate",
    "main",
    "money_rub_per_unit",
    "split_samples",
]
