
from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    ConvergenceError,
)

from collections.abc import Sequence
from dataclasses import dataclass

from backend.contexts.optimization.domain.verification_types import CandidateCheck, RoundReport
from backend.contexts.surrogate.domain.crm import spearman


def absolute_deviation_criterion(tolerance: float):
    if tolerance < 0.0:
        raise ConvergenceError(f"tolerance {tolerance} is negative")

    def criterion(checks: Sequence[CandidateCheck]) -> bool:
        if not checks:
            raise ConvergenceError("the criterion is undefined on an empty round")
        return all(abs(check.relative_deviation) <= tolerance for check in checks)

    return criterion


def rank_agreement_criterion(minimum: float):
    if not -1.0 <= minimum <= 1.0:
        raise ConvergenceError(f"correlation threshold {minimum} is outside [-1, 1]")

    def criterion(checks: Sequence[CandidateCheck]) -> bool:
        if not checks:
            raise ConvergenceError("the criterion is undefined on an empty round")
        if len(checks) < 2:
            raise ConvergenceError(
                "rank agreement requires at least two candidates in a round"
            )
        predicted = [check.predicted_npv for check in checks]
        actual = [check.actual_npv for check in checks]
        return spearman(actual, predicted) >= minimum

    return criterion


def both_criterion(tolerance: float, minimum: float):
    left = absolute_deviation_criterion(tolerance)
    right = rank_agreement_criterion(minimum)

    def criterion(checks: Sequence[CandidateCheck]) -> bool:
        return left(checks) and right(checks)

    return criterion


def trust_was_justified(checks: Sequence[CandidateCheck], *, regret_tolerance: float) -> bool:
    if not checks:
        raise ConvergenceError("the ground truth is undefined on an empty round")
    if regret_tolerance < 0.0:
        raise ConvergenceError(f"regret tolerance {regret_tolerance} is negative")

    predicted_best = max(checks, key=lambda check: check.predicted_npv)
    actual_best = max(check.actual_npv for check in checks)
    if actual_best == 0.0:
        raise ConvergenceError("the best actual NPV is zero: the regret is undefined")

    shortfall = (actual_best - predicted_best.actual_npv) / abs(actual_best)
    return shortfall <= regret_tolerance


@dataclass(frozen=True, slots=True)
class CriterionMeasurement:
    name: str
    threshold: float
    n_rounds: int
    false_expansions: int
    missed_expansions: int
    correct_expansions: int
    correct_contractions: int

    @property
    def agreements(self) -> int:
        return self.correct_expansions + self.correct_contractions

    @property
    def agreement_rate(self) -> float:
        return self.agreements / self.n_rounds if self.n_rounds else 0.0

    @property
    def rank_key(self) -> tuple[int, int, float]:
        return (self.false_expansions, -self.correct_expansions, -self.agreement_rate)


@dataclass(frozen=True, slots=True)
class CriterionSweep:
    name: str
    measurements: tuple[CriterionMeasurement, ...]

    def __post_init__(self) -> None:
        if not self.measurements:
            raise ConvergenceError(f"{self.name}: empty threshold grid")

    @property
    def best(self) -> CriterionMeasurement:
        return min(self.measurements, key=lambda item: item.rank_key)

    @property
    def stable(self) -> bool:
        ordered = sorted(self.measurements, key=lambda item: item.threshold)
        index = ordered.index(self.best)
        neighbours = [
            ordered[i]
            for i in (index - 1, index + 1)
            if 0 <= i < len(ordered)
        ]
        if not neighbours:
            return False
        limit = max(1, 2 * self.best.false_expansions)
        return all(item.false_expansions <= limit for item in neighbours)


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    sweeps: tuple[CriterionSweep, ...]
    n_rounds: int
    regret_tolerance: float
    synthetic_inputs: bool

    def sweep_of(self, name: str) -> CriterionSweep:
        for sweep in self.sweeps:
            if sweep.name == name:
                return sweep
        raise ConvergenceError(f"candidate {name!r} is not in the report")

    @property
    def winner(self) -> CriterionMeasurement | None:
        if self.synthetic_inputs or self.n_rounds < 2:
            return None
        return min(
            (sweep.best for sweep in self.sweeps), key=lambda item: item.rank_key
        )

    @property
    def verdict(self) -> str:
        if self.synthetic_inputs:
            return (
                "the table is marked synthetic: a criterion calibrated on invented data "
                "is a choice disguised as a measurement (rule 4), no verdict is "
                "issued"
            )
        if self.n_rounds < 2:
            return (
                f"rounds {self.n_rounds}: on a single round the criterion does not "
                f"discriminate, the measurement did not take place"
            )
        best = self.winner
        assert best is not None
        return (
            f"{best.name} with threshold {best.threshold:g}: false expansions "
            f"{best.false_expansions}, correct {best.correct_expansions} "
            f"out of {self.n_rounds} rounds"
        )


def measure_criteria(
    rounds: Sequence[RoundReport],
    *,
    regret_tolerance: float,
    deviation_thresholds: Sequence[float] = (0.01, 0.02, 0.05, 0.10, 0.20),
    rank_thresholds: Sequence[float] = (0.0, 0.3, 0.5, 0.7, 0.9),
    synthetic_inputs: bool = False,
) -> CalibrationReport:
    if not rounds:
        raise ConvergenceError("a measurement on an empty loop history is impossible")
    if not deviation_thresholds or not rank_thresholds:
        raise ConvergenceError("an empty threshold grid measures nothing")

    truth = [
        trust_was_justified(report.checks, regret_tolerance=regret_tolerance)
        for report in rounds
    ]

    def measure(name: str, threshold: float, criterion) -> CriterionMeasurement:
        false_expansions = 0
        missed_expansions = 0
        correct_expansions = 0
        correct_contractions = 0
        for report, justified in zip(rounds, truth):
            said_converged = criterion(report.checks)
            if said_converged and justified:
                correct_expansions += 1
            elif said_converged and not justified:
                false_expansions += 1
            elif justified:
                missed_expansions += 1
            else:
                correct_contractions += 1
        return CriterionMeasurement(
            name=name,
            threshold=threshold,
            n_rounds=len(rounds),
            false_expansions=false_expansions,
            missed_expansions=missed_expansions,
            correct_expansions=correct_expansions,
            correct_contractions=correct_contractions,
        )

    deviation = CriterionSweep(
        name="absolute_deviation",
        measurements=tuple(
            measure("absolute_deviation", t, absolute_deviation_criterion(t))
            for t in deviation_thresholds
        ),
    )
    rank = CriterionSweep(
        name="rank_agreement",
        measurements=tuple(
            measure("rank_agreement", t, rank_agreement_criterion(t))
            for t in rank_thresholds
        ),
    )
    best_rank = rank.best.threshold
    combined = CriterionSweep(
        name="both",
        measurements=tuple(
            measure("both", t, both_criterion(t, best_rank))
            for t in deviation_thresholds
        ),
    )

    return CalibrationReport(
        sweeps=(deviation, rank, combined),
        n_rounds=len(rounds),
        regret_tolerance=regret_tolerance,
        synthetic_inputs=synthetic_inputs,
    )
