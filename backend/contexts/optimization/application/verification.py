
from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    VerificationError,
)

from dataclasses import dataclass
from typing import Protocol, Sequence

from backend.core.contracts import OptimizerResult, ScenarioViolation, Theta

from backend.contexts.optimization.domain.optimizer import optimize


@dataclass(frozen=True, slots=True)
class SurrogateVerdict:
    predicted_npv: float
    ood_score: float

    def __post_init__(self) -> None:
        if self.ood_score < 0.0:
            raise VerificationError(f"ood_score={self.ood_score} отрицателен")


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
            raise VerificationError("истинный ЧДД без run_id: строка ни с чем не связана")


class TruthOracle(Protocol):
    def __call__(self, theta: Theta) -> TruthVerdict: ...


class Retrainer(Protocol):
    def __call__(self, observations: tuple["CandidateCheck", ...]) -> SurrogateVersion: ...


class ConvergenceCriterion(Protocol):
    def __call__(self, checks: Sequence["CandidateCheck"]) -> bool: ...


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
                f"{self.run_id}: фактический ЧДД равен нулю, "
                f"относительное отклонение не определено"
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
                f"раунд {self.index}: ни одного проверенного кандидата"
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
            raise VerificationError("цикл без единого раунда")

    @property
    def table(self) -> tuple[CandidateCheck, ...]:
        return tuple(check for report in self.rounds for check in report.checks)

    @property
    def total_runs(self) -> int:
        return len(self.table)

    @property
    def converged_rounds(self) -> int:
        return sum(1 for report in self.rounds if report.converged)


def trust_region_objective(surrogate: SurrogateVersion, tau: float):
    if tau < 0.0:
        raise VerificationError(f"порог области доверия τ={tau} отрицателен")

    def objective(theta: Theta) -> OptimizerResult:
        verdict = surrogate(theta)
        inside = verdict.ood_score <= tau
        violations = (
            ()
            if inside
            else (
                ScenarioViolation(
                    scenario_id="trust_region",
                    regret=verdict.ood_score - tau,
                    what=f"ood_score {verdict.ood_score:.4f} > τ {tau:.4f}",
                ),
            )
        )
        return OptimizerResult(
            objective=verdict.predicted_npv,
            feasible=inside,
            violations_by_scenario=violations,
            provenance={
                "surrogate_version": str(surrogate.version),
                "tau": repr(tau),
            },
        )

    return objective


def run_verification_loop(
    surrogate: SurrogateVersion,
    truth: TruthOracle,
    retrain: Retrainer,
    criterion: ConvergenceCriterion,
    start_theta: Theta,
    *,
    seed: int,
    initial_tau: float,
    runs_per_round: int,
    max_rounds: int,
    optimizer_evaluations_per_round: int,
    tau_expansion: float = 2.0,
    tau_contraction: float = 0.5,
) -> VerificationReport:
    if runs_per_round < 1:
        raise VerificationError(f"прогонов на раунд {runs_per_round} < 1")
    if max_rounds < 1:
        raise VerificationError(f"раундов {max_rounds} < 1")
    if optimizer_evaluations_per_round < 1:
        raise VerificationError(
            f"бюджет оптимизатора {optimizer_evaluations_per_round} < 1"
        )
    if initial_tau < 0.0:
        raise VerificationError(f"начальный τ={initial_tau} отрицателен")
    if not tau_expansion > 1.0:
        raise VerificationError(f"расширение области {tau_expansion} не больше 1")
    if not 0.0 < tau_contraction < 1.0:
        raise VerificationError(f"сужение области {tau_contraction} вне (0, 1)")

    tau = float(initial_tau)
    current = surrogate
    rounds: list[RoundReport] = []
    stop_reason = f"пройдены все {max_rounds} раундов"

    for index in range(max_rounds):
        objective = trust_region_objective(current, tau)
        search = optimize(
            objective,
            start_theta,
            seed=seed + index,
            max_evaluations=optimizer_evaluations_per_round,
        )

        feasible = [item for item in search.history if item.result.feasible]
        if not feasible:
            stop_reason = (
                f"раунд {index}: внутри области доверия τ={tau:.6f} не нашлось "
                f"ни одного кандидата из {search.evaluations} оценённых"
            )
            break

        top = sorted(feasible, key=lambda item: -item.result.objective)[:runs_per_round]

        checks: list[CandidateCheck] = []
        for item in top:
            verdict = current(item.theta)
            observed = truth(item.theta)
            checks.append(
                CandidateCheck(
                    round_index=index,
                    theta=item.theta,
                    predicted_npv=item.result.objective,
                    actual_npv=observed.npv,
                    ood_score=verdict.ood_score,
                    tau=tau,
                    surrogate_version=current.version,
                    run_id=observed.run_id,
                    canonical_schedule_hash=observed.canonical_schedule_hash,
                )
            )

        converged = criterion(checks)
        next_tau = tau * (tau_expansion if converged else tau_contraction)
        retrained = False
        if not converged:
            current = retrain(tuple(checks))
            retrained = True

        rounds.append(
            RoundReport(
                index=index,
                tau=tau,
                next_tau=next_tau,
                checks=tuple(checks),
                converged=converged,
                retrained=retrained,
                surrogate_version=checks[0].surrogate_version,
                optimizer_evaluations=search.evaluations,
                feasible_candidates=len(feasible),
            )
        )
        tau = next_tau

    if not rounds:
        raise VerificationError(
            f"цикл не сделал ни одного раунда: {stop_reason}"
        )

    table = tuple(check for report in rounds for check in report.checks)
    best = max(table, key=lambda check: check.actual_npv)

    reevaluation = current(best.theta)
    inside_final_region = reevaluation.ood_score <= tau
    still_agrees = criterion(
        [
            CandidateCheck(
                round_index=best.round_index,
                theta=best.theta,
                predicted_npv=reevaluation.predicted_npv,
                actual_npv=best.actual_npv,
                ood_score=reevaluation.ood_score,
                tau=tau,
                surrogate_version=current.version,
                run_id=best.run_id,
                canonical_schedule_hash=best.canonical_schedule_hash,
            )
        ]
    )

    return VerificationReport(
        rounds=tuple(rounds),
        best=best,
        self_consistent=bool(inside_final_region and still_agrees),
        final_tau=tau,
        final_surrogate_version=current.version,
        reevaluation=reevaluation,
        stop_reason=stop_reason,
    )
