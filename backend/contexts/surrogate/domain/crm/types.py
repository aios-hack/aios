from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.surrogate.domain.errors import CrmError


DEFAULT_TAU_INTERVALS = 1.0
DEFAULT_RIDGE = 1e2
DEFAULT_TRAIN_FRACTION = 0.75
_MAX_SWEEPS = 200
_CONVERGENCE_TOLERANCE = 1e-9
_MIN_TAU = 1e-6


@dataclass(frozen=True, slots=True)
class CrmSplit:
    train_intervals: int
    n_intervals: int

    def __post_init__(self) -> None:
        if self.n_intervals <= 0:
            raise CrmError("n_intervals must be positive")
        if not (0 < self.train_intervals < self.n_intervals):
            raise CrmError(
                f"train_intervals={self.train_intervals} must lie strictly inside "
                f"0…{self.n_intervals}: otherwise no hold-out part exists"
            )

    @property
    def holdout_intervals(self) -> int:
        return self.n_intervals - self.train_intervals

    @property
    def train_steps(self) -> range:
        return range(self.train_intervals)

    @property
    def holdout_steps(self) -> range:
        return range(self.train_intervals, self.n_intervals)


@dataclass(frozen=True, slots=True)
class CrmMetrics:
    n_points: int
    r2: float
    mae: float
    median_relative_error: float
    spearman_rank_correlation: float


@dataclass(frozen=True, slots=True)
class CrmModel:
    producers: tuple[str, ...]
    injectors: tuple[str, ...]
    allocation: tuple[tuple[float, ...], ...]
    base_liquid: tuple[float, ...]
    tau_intervals: float
    split: CrmSplit
    material_balance_enforced: bool

    def allocation_of(self, producer: str, injector: str) -> float:
        try:
            row = self.producers.index(producer)
            column = self.injectors.index(injector)
        except ValueError as error:
            raise CrmError(f"pair ({producer!r}, {injector!r}) is outside the model axes") from error
        return self.allocation[row][column]

    def injector_allocation_sums(self) -> tuple[float, ...]:
        return tuple(
            sum(self.allocation[row][column] for row in range(len(self.producers)))
            for column in range(len(self.injectors))
        )

    def max_injector_allocation_sum(self) -> float:
        sums = self.injector_allocation_sums()
        return max(sums) if sums else 0.0


@dataclass(frozen=True, slots=True)
class CrmEvaluation:
    model: CrmModel
    holdout: CrmMetrics
    train: CrmMetrics

    @property
    def generalization_gap(self) -> float:
        return self.train.r2 - self.holdout.r2


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    baseline: CrmMetrics
    candidate: CrmMetrics
    beats_baseline: bool
    rank_correlation_gain: float


__all__ = [
    "BaselineComparison",
    "CrmEvaluation",
    "CrmMetrics",
    "CrmModel",
    "CrmSplit",
    "DEFAULT_RIDGE",
    "DEFAULT_TAU_INTERVALS",
    "DEFAULT_TRAIN_FRACTION",
]
