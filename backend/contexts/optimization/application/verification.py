
from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    VerificationError,
)

from backend.contexts.policy.domain.policy import OptimizerResult, ScenarioViolation, Theta

from backend.contexts.optimization.domain.optimizer import optimize
from backend.contexts.optimization.domain.verification_types import (
    CandidateCheck,
    ConvergenceCriterion,
    Retrainer,
    RoundReport,
    SurrogateVerdict,
    SurrogateVersion,
    TruthOracle,
    TruthVerdict,
    VerificationReport,
)


def trust_region_objective(surrogate: SurrogateVersion, tau: float):
    if tau < 0.0:
        raise VerificationError(f"trust region threshold τ={tau} is negative")

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
        raise VerificationError(f"runs per round {runs_per_round} < 1")
    if max_rounds < 1:
        raise VerificationError(f"rounds {max_rounds} < 1")
    if optimizer_evaluations_per_round < 1:
        raise VerificationError(
            f"optimizer budget {optimizer_evaluations_per_round} < 1"
        )
    if initial_tau < 0.0:
        raise VerificationError(f"initial τ={initial_tau} is negative")
    if not tau_expansion > 1.0:
        raise VerificationError(f"region expansion {tau_expansion} is not greater than 1")
    if not 0.0 < tau_contraction < 1.0:
        raise VerificationError(f"region contraction {tau_contraction} is outside (0, 1)")

    tau = float(initial_tau)
    current = surrogate
    rounds: list[RoundReport] = []
    stop_reason = f"all {max_rounds} rounds completed"

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
                f"round {index}: inside the trust region τ={tau:.6f} not a single "
                f"candidate was found out of {search.evaluations} evaluated"
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
            f"the loop made no rounds at all: {stop_reason}"
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
    "run_verification_loop",
    "trust_region_objective",
]
