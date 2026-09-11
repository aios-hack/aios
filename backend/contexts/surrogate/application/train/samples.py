from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

from backend.contexts.simulation.infrastructure.dataset import DatasetSample
from backend.contexts.surrogate.application.model import (
    TrainingExample,
)
from backend.contexts.surrogate.domain.errors import TrainingCommandError
from backend.contexts.surrogate.domain.features import ScheduleFeatureizer
from backend.contexts.surrogate.infrastructure.model_z_context import (
    ModelZFeatureArtifact,
)


@dataclass(frozen=True, slots=True)
class Split:
    train: tuple[DatasetSample, ...]
    validation: tuple[DatasetSample, ...]
    test: tuple[DatasetSample, ...]


def split_samples(
    samples: Sequence[DatasetSample],
    *,
    validation_fraction: float,
    test_fraction: float,
    seed: int,
) -> Split:
    if len(samples) < 8:
        raise TrainingCommandError("train/validation/test require at least 8 runs")
    if not (0.0 < validation_fraction < 1.0 and 0.0 < test_fraction < 1.0):
        raise TrainingCommandError("the validation/test fractions must lie in (0, 1)")
    if validation_fraction + test_fraction >= 1.0:
        raise TrainingCommandError("the validation/test fractions leave no train split")
    order = list(range(len(samples)))
    random.Random(seed).shuffle(order)
    n_test = max(1, round(len(samples) * test_fraction))
    n_validation = max(1, round(len(samples) * validation_fraction))
    test_ids = set(order[:n_test])
    validation_ids = set(order[n_test : n_test + n_validation])
    train = tuple(
        sample
        for index, sample in enumerate(samples)
        if index not in test_ids and index not in validation_ids
    )
    validation = tuple(
        sample for index, sample in enumerate(samples) if index in validation_ids
    )
    test = tuple(sample for index, sample in enumerate(samples) if index in test_ids)
    if len(train) < 8:
        raise TrainingCommandError("the train split is too small for an independent lambda estimate")
    return Split(train=train, validation=validation, test=test)


def _examples(
    samples: Iterable[DatasetSample], artifact: ModelZFeatureArtifact
) -> tuple[TrainingExample, ...]:
    featureizer = ScheduleFeatureizer()
    result: list[TrainingExample] = []
    for sample in samples:
        if sample.response is None:
            raise TrainingCommandError(
                f"scenario {sample.metadata.scenario_id} contains no ResponseArtifact"
            )
        model_input = replace(
            featureizer.transform(sample.schedule, artifact.context),
            lambda_edges=(),
        )
        result.append(
            TrainingExample(
                input=model_input,
                response=sample.response,
            )
        )
    return tuple(result)


__all__ = [
    "Split",
    "_examples",
    "split_samples",
]
