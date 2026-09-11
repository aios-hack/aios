from __future__ import annotations

from typing import Mapping, Sequence

from backend.contexts.surrogate.domain.crm.statistics import _filtered
from backend.contexts.surrogate.domain.crm.types import (
    BaselineComparison,
    CrmMetrics,
    CrmModel,
)
from backend.contexts.surrogate.domain.errors import CrmError


def predict_liquid(
    model: CrmModel, injection_by_well: Mapping[str, Sequence[float]], n_intervals: int
) -> dict[str, tuple[float, ...]]:
    missing = [well for well in model.injectors if well not in injection_by_well]
    if missing:
        raise CrmError(f"no injection programme for injectors: {sorted(missing)}")
    filtered = {
        well: _filtered(tuple(injection_by_well[well][:n_intervals]), model.tau_intervals)
        for well in model.injectors
    }
    result: dict[str, tuple[float, ...]] = {}
    for index, producer in enumerate(model.producers):
        row = model.allocation[index]
        intercept = model.base_liquid[index]
        result[producer] = tuple(
            intercept
            + sum(
                coefficient * filtered[well][k]
                for coefficient, well in zip(row, model.injectors)
            )
            for k in range(n_intervals)
        )
    return result


def compare_to_baseline(
    baseline: CrmMetrics, candidate: CrmMetrics
) -> BaselineComparison:
    if baseline.n_points != candidate.n_points:
        raise CrmError(
            "comparison with the baseline requires the very same sample: "
            f"{baseline.n_points} against {candidate.n_points}"
        )
    gain = (
        candidate.spearman_rank_correlation - baseline.spearman_rank_correlation
    )
    return BaselineComparison(
        baseline=baseline,
        candidate=candidate,
        beats_baseline=gain > 0.0,
        rank_correlation_gain=gain,
    )


__all__ = [
    "compare_to_baseline",
    "predict_liquid",
]
