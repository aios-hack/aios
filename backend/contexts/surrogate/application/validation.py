from __future__ import annotations

from backend.contexts.surrogate.domain.validation_pass import (
    _validate,
)


from backend.contexts.surrogate.domain.model_types import (
    TARGET_NAMES,
    TrainingExample,
)

from backend.contexts.surrogate.domain.vectorize import (
    _targets,
)
from backend.contexts.surrogate.domain.errors import (
    SurrogateModelError,
)
from typing import (
    Iterable,
    Sequence,
)
import torch


def split_examples(
    examples: Sequence[TrainingExample],
    *,
    validation_fraction: float = 0.15,
    test_fraction: float = 0.15,
    seed: int = 20260816,
) -> tuple[tuple[TrainingExample, ...], tuple[TrainingExample, ...], tuple[TrainingExample, ...]]:
    if not (0.0 < validation_fraction < 1.0 and 0.0 < test_fraction < 1.0):
        raise SurrogateModelError("validation_fraction/test_fraction must lie in (0, 1)")
    if validation_fraction + test_fraction >= 1.0:
        raise SurrogateModelError("no scenarios are left for train")
    if len(examples) < 7:
        raise SurrogateModelError("train/validation/test require at least 7 scenarios")
    generator = torch.Generator().manual_seed(seed)
    order = torch.randperm(len(examples), generator=generator).tolist()
    n_test = max(1, round(len(examples) * test_fraction))
    n_validation = max(1, round(len(examples) * validation_fraction))
    test_ids = set(order[:n_test])
    validation_ids = set(order[n_test : n_test + n_validation])
    train = tuple(item for index, item in enumerate(examples) if index not in test_ids | validation_ids)
    validation = tuple(item for index, item in enumerate(examples) if index in validation_ids)
    test = tuple(item for index, item in enumerate(examples) if index in test_ids)
    return train, validation, test


def target_mae(
    model: "TrajectorySurrogate",
    examples: Iterable[TrainingExample],
) -> dict[str, float]:
    totals = [0.0] * len(TARGET_NAMES)
    count = 0
    for example in examples:
        predicted = model.predict(example.input).output
        actual = torch.expm1(_targets(example))
        estimate = torch.tensor(
            [
                [float(getattr(node, name)) for name in TARGET_NAMES]
                for node in predicted.nodes
            ]
        )
        error = (actual - estimate).abs().sum(dim=0)
        totals = [total + float(value) for total, value in zip(totals, error)]
        count += actual.shape[0]
    if count == 0:
        raise SurrogateModelError("metrics are not computed on an empty set")
    return {name: total / count for name, total in zip(TARGET_NAMES, totals)}


__all__ = [
    "split_examples",
    "target_mae",
]
