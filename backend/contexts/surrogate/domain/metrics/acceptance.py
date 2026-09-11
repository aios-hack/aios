from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.surrogate.domain.errors import MetricsError
from backend.contexts.surrogate.domain.metrics.ranking import NpvRankingMetrics
from backend.contexts.surrogate.domain.metrics.state import StateMetrics
from backend.contexts.surrogate.domain.metrics.watercut import WatercutMetrics


@dataclass(frozen=True, slots=True)
class SurrogateMetrics:
    ranking: NpvRankingMetrics
    state: StateMetrics
    watercut: WatercutMetrics
    synthetic_inputs: bool = False


@dataclass(frozen=True, slots=True)
class AcceptanceVerdict:
    accepted: bool
    model_spearman: float
    baseline_spearman: float
    reason: str

    @property
    def margin(self) -> float:
        return self.model_spearman - self.baseline_spearman


def accept_against_baseline(
    model: NpvRankingMetrics,
    baseline: NpvRankingMetrics,
    *,
    synthetic_inputs: bool = False,
) -> AcceptanceVerdict:
    if model.n_candidates != baseline.n_candidates:
        raise MetricsError(
            f"comparison on different samples: {model.n_candidates} against "
            f"{baseline.n_candidates} candidates"
        )
    if synthetic_inputs:
        return AcceptanceVerdict(
            accepted=False,
            model_spearman=model.spearman_rank_correlation,
            baseline_spearman=baseline.spearman_rank_correlation,
            reason=(
                "the metrics were computed on synthetic inputs: rule 4 forbids presenting "
                "them as a quality measurement, so no verdict is issued"
            ),
        )

    margin = model.spearman_rank_correlation - baseline.spearman_rank_correlation
    if margin > 0.0:
        return AcceptanceVerdict(
            accepted=True,
            model_spearman=model.spearman_rank_correlation,
            baseline_spearman=baseline.spearman_rank_correlation,
            reason=(
                f"rank correlation {model.spearman_rank_correlation:.4f} is above "
                f"the CRM baseline {baseline.spearman_rank_correlation:.4f} "
                f"by {margin:.4f}"
            ),
        )
    return AcceptanceVerdict(
        accepted=False,
        model_spearman=model.spearman_rank_correlation,
        baseline_spearman=baseline.spearman_rank_correlation,
        reason=(
            f"rank correlation {model.spearman_rank_correlation:.4f} is not above "
            f"the CRM baseline {baseline.spearman_rank_correlation:.4f}: "
            f"the model is rejected (§5.5)"
        ),
    )


__all__ = [
    "AcceptanceVerdict",
    "SurrogateMetrics",
    "accept_against_baseline",
]
