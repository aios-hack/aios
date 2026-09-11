from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.contexts.surrogate.domain.crm import spearman
from backend.contexts.surrogate.domain.errors import MetricsError


@dataclass(frozen=True, slots=True)
class NpvRankingMetrics:
    n_candidates: int
    spearman_rank_correlation: float
    precision_at_k: dict[int, float]
    regret_at_k_rub: dict[int, float]

    def __post_init__(self) -> None:
        if self.n_candidates < 2:
            raise MetricsError(
                f"ranking over {self.n_candidates} candidates is undefined"
            )


def _top_k_indices(values: Sequence[float], k: int) -> list[int]:
    return sorted(range(len(values)), key=lambda i: (-values[i], i))[:k]


def ranking_metrics(
    actual_npv: Sequence[float],
    predicted_npv: Sequence[float],
    *,
    k_values: Sequence[int] = (1, 3, 5),
) -> NpvRankingMetrics:
    if len(actual_npv) != len(predicted_npv):
        raise MetricsError(
            f"{len(actual_npv)} candidates by fact and {len(predicted_npv)} by forecast"
        )
    n = len(actual_npv)
    if n < 2:
        raise MetricsError(f"ranking over {n} candidates is undefined")

    precision: dict[int, float] = {}
    regret: dict[int, float] = {}
    best_actual = max(actual_npv)

    for k in k_values:
        if k < 1:
            raise MetricsError(f"k={k} < 1")
        if k > n:
            continue
        predicted_top = _top_k_indices(predicted_npv, k)
        actual_top = set(_top_k_indices(actual_npv, k))
        precision[k] = len(set(predicted_top) & actual_top) / k
        regret[k] = best_actual - max(actual_npv[i] for i in predicted_top)

    if not precision:
        raise MetricsError(f"no k out of {tuple(k_values)} fits into {n} candidates")

    return NpvRankingMetrics(
        n_candidates=n,
        spearman_rank_correlation=spearman(actual_npv, predicted_npv),
        precision_at_k=precision,
        regret_at_k_rub=regret,
    )


__all__ = [
    "NpvRankingMetrics",
    "ranking_metrics",
]
