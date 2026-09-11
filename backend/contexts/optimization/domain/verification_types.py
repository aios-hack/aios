from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from backend.contexts.optimization.domain.errors import VerificationError
from backend.contexts.policy.domain.policy import Theta


@dataclass(frozen=True, slots=True)
class SurrogateVerdict:
    predicted_npv: float
    ood_score: float

    def __post_init__(self) -> None:
        if self.ood_score < 0.0:
            raise VerificationError(f"ood_score={self.ood_score} is negative")


class SurrogateVersion(Protocol):
    version: int

    def __call__(self, theta: Theta) -> SurrogateVerdict: ...


@dataclass(frozen=True, slots=True)
class TruthVerdict:
    npv: float
    run_id: str
    canonical_schedule_hash: str

    def __post_init__(self) -> None:
        if not self.run_id:
            raise VerificationError("true NPV without run_id: the row is not linked to anything")


class TruthOracle(Protocol):
    def __call__(self, theta: Theta) -> TruthVerdict: ...


class Retrainer(Protocol):
    def __call__(self, observations: tuple[CandidateCheck, ...]) -> SurrogateVersion: ...


class ConvergenceCriterion(Protocol):
    def __call__(self, checks: Sequence[CandidateCheck]) -> bool: ...


@dataclass(frozen=True, slots=True)
class CandidateCheck:
    round_index: int
    theta: Theta
    predicted_npv: float
    actual_npv: float
    ood_score: float
    tau: float
    surrogate_version: int
    run_id: str
    canonical_schedule_hash: str

    @property
    def deviation(self) -> float:
        return self.predicted_npv - self.actual_npv

    @property
    def relative_deviation(self) -> float:
        if self.actual_npv == 0.0:
            raise VerificationError(
                f"{self.run_id}: the actual NPV is zero, "
                f"the relative deviation is undefined"
            )
        return self.deviation / abs(self.actual_npv)


@dataclass(frozen=True, slots=True)
class RoundReport:
    index: int
    tau: float
    next_tau: float
    checks: tuple[CandidateCheck, ...]
    converged: bool
    retrained: bool
    surrogate_version: int
    optimizer_evaluations: int
    feasible_candidates: int

    def __post_init__(self) -> None:
        if not self.checks:
            raise VerificationError(
                f"round {self.index}: not a single verified candidate"
            )


@dataclass(frozen=True, slots=True)
class VerificationReport:
    rounds: tuple[RoundReport, ...]
    best: CandidateCheck
    self_consistent: bool
    final_tau: float
    final_surrogate_version: int
    reevaluation: SurrogateVerdict
    stop_reason: str

    def __post_init__(self) -> None:
        if not self.rounds:
            raise VerificationError("loop without a single round")

    @property
    def table(self) -> tuple[CandidateCheck, ...]:
        return tuple(check for report in self.rounds for check in report.checks)

    @property
    def total_runs(self) -> int:
        return len(self.table)

    @property
    def converged_rounds(self) -> int:
        return sum(1 for report in self.rounds if report.converged)


__all__ = [
    "CandidateCheck",
    "ConvergenceCriterion",
    "Retrainer",
    "RoundReport",
    "SurrogateVerdict",
    "SurrogateVersion",
    "TruthOracle",
    "TruthVerdict",
    "VerificationReport",
]
