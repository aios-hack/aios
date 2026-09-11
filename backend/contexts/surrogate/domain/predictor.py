from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.contexts.robustness.domain.ood import ScoredPrediction
from backend.contexts.surrogate.domain.features import SurrogateInput


@runtime_checkable
class TrajectoryPredictor(Protocol):
    version: str
    wells: tuple[str, ...]

    def predict(self, candidate: SurrogateInput) -> ScoredPrediction: ...


__all__ = ["TrajectoryPredictor"]
