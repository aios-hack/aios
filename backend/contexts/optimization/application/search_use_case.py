from __future__ import annotations

import json
import logging
import math
import sys
import time

from backend.contexts.constraints.application.cases import load_case
from backend.contexts.economics.application.base_case import load_response_artifact
from backend.contexts.optimization.application.baseline_search import (
    _search_near_baseline,
    _search_theta,
)
from backend.contexts.optimization.application.environment import (
    OutOfDomainScheduleError,
    PhysicallyImpossibleScheduleError,
    load_environment,
    make_evaluator,
)
from backend.contexts.optimization.application.finalist_selection import evaluate_finalists
from backend.contexts.optimization.application.search_provenance import build_search_provenance
from backend.contexts.optimization.application.policy_factory import make_policy
from backend.contexts.optimization.application.search_config import (
    BASE_NPV,
    BUDGET,
    CONSTRAINTS,
    FINAL_CAP,
    RESPONSE,
    RISK_AVERSION_BETA,
    SEARCH_CAP,
    SEARCH_DIAGNOSTICS,
    SEARCH_RESULT,
    SEED,
    _artifact_sha256,
)
from backend.contexts.optimization.application.water_repair import _repair_predicted_water_balance
from backend.contexts.optimization.domain.errors import (
    BhpToleranceError,
    ConnectivitySearchError,
    OpmBudgetError,
    SearchRunError,
)
from backend.contexts.optimization.domain.gates.bhp_tolerance import (
    BhpTolerance,
    SURROGATE_METRICS_FORMAT,
    _bhp_tolerance_decision,
    bhp_exceedance_bar,
    surrogate_blocking_violations,
)
from backend.contexts.optimization.domain.gates.incumbent import (
    IncumbentRegistry,
    incumbent_gate_passed,
)
from backend.contexts.optimization.domain.gates.ood_threshold import (
    _ood_threshold_decision,
    _soft_penalty_enabled,
    _soft_penalty_rate,
)
from backend.contexts.optimization.domain.gates.opm_budget import (
    RUN_CLOCK,
    RunBudget,
    close_run_clock,
    read_opm_budget,
    start_run_clock,
)
from backend.contexts.optimization.domain.injection_transfer import (
    _baseline_injection_rates,
    _connectivity_groups,
    _injection_transfer_plan,
    _lambda_connectivity,
    _transfer_injection,
)
from backend.contexts.optimization.domain.optimizer import optimize
from backend.contexts.optimization.domain.search_limits import (
    DEFAULT_FINAL_CAP,
    DEFAULT_SEARCH_CAP,
    MISSING_SIGMA,
)
from backend.contexts.optimization.domain.selection import SearchOutcome, select_finalist
from backend.contexts.optimization.infrastructure.artifacts import (
    resolve_lambda_selection,
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.contexts.optimization.infrastructure.diagnostics_journal import (
    _evaluation_cards,
    _write_diagnostics_head,
    _write_diagnostics_tail,
    candidate_card,
)
from backend.contexts.policy.domain.fixed_point import resolve
from backend.contexts.policy.domain.policy import OptimizerResult, ScenarioViolation
from backend.contexts.schedule.domain.validate import validate_static
from backend.shared.resources import chdd_python_dir, model_z_dir
from dataclasses import replace
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


logger = logging.getLogger(__name__)


def run_search(
    *,
    budget: int = BUDGET,
    case_path: Path | None = None,
    search_cap: int = SEARCH_CAP,
    final_cap: int = FINAL_CAP,
    seed: int = SEED,
) -> SearchOutcome:
    if search_cap <= 0 or final_cap <= 0:
        raise SearchRunError(
            f"the fixed-point cap must be positive: "
            f"search {search_cap}, final {final_cap}"
        )
    start_run_clock()
    artifacts = resolve_runtime_artifacts()
    if artifacts.scenario_ood is None:
        raise SearchRunError("production search requires a versioned scenario OOD artifact")
    lambda_selection = resolve_lambda_selection(
        feature_context=artifacts.feature_context
    )
    constraints_path = Path(case_path) if case_path is not None else CONSTRAINTS
    constraints = load_case(constraints_path)
    threshold_decision = _ood_threshold_decision()
    bhp_tolerance = _bhp_tolerance_decision()
    soft_penalty = _soft_penalty_enabled()
    penalty_rate = _soft_penalty_rate() if soft_penalty else 0.0
    env = load_environment(
        model_dir=model_z_dir(),
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        npv_calibration_path=artifacts.npv_calibration,
        scenario_ood_path=artifacts.scenario_ood,
        lambda_path=lambda_selection.path,
        constraints=constraints,
        ood_threshold=threshold_decision.value,
        ood_soft_penalty=soft_penalty,
        ood_penalty_per_unit=penalty_rate,
    )
    validate_runtime_economic_head(artifacts, env.npv_head)
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)
    final_evaluator = (
        make_evaluator(env, with_sigma=True)
        if RISK_AVERSION_BETA > 0.0
        else evaluator
    )
    search_start = _search_theta(constraints)
    provenance = build_search_provenance(
        env=env,
        artifacts=artifacts,
        constraints=constraints,
        constraints_path=constraints_path,
        lambda_selection=lambda_selection,
        threshold_decision=threshold_decision,
        bhp_tolerance=bhp_tolerance,
        soft_penalty=soft_penalty,
        penalty_rate=penalty_rate,
        search_cap=search_cap,
        final_cap=final_cap,
        seed=seed,
        artifact_sha256=_artifact_sha256,
    )
    calls = {"n": 0, "best": float("-inf")}
    cards: list[dict[str, object]] = []
    registry = IncumbentRegistry()
    scenario_ood_threshold = (
        float(env.scenario_ood.threshold) if env.scenario_ood is not None else None
    )

    def objective(theta) -> OptimizerResult:
        try:
            result = resolve(make_policy(env, theta, {}), evaluator, initial, search_cap)
        except (OutOfDomainScheduleError, PhysicallyImpossibleScheduleError) as error:
            calls["n"] += 1
            rejection = {
                "scenario_id": "surrogate-rejected",
                "regret": 1.0,
                "what": str(error),
            }
            cards.append(
                candidate_card(
                    schedule_hash="",
                    theta=dict(theta.values),
                    npv_predicted=None,
                    npv_parts={},
                    ood_score=getattr(error, "score", None),
                    ood_worst=None,
                    scenario_ood=scenario_ood_threshold,
                    physics=getattr(error, "counts", {}) or {},
                    static_violations=None,
                    dynamic_blocking_violations=None,
                    feasible=False,
                    violations=[rejection],
                    strategy="cma-es",
                    ood_exceedances=getattr(error, "exceedances", ()) or (),
                )
            )
            return OptimizerResult(
                objective=-math.inf, feasible=False,
                violations_by_scenario=(ScenarioViolation(
                    scenario_id="surrogate-rejected", regret=1.0, what=str(error),
                ),), provenance=provenance,
            )
        npv = result.npv
        static = validate_static(result.schedule, env.constraints)
        violations: list[ScenarioViolation] = []
        if static.violations:
            violations.append(
                ScenarioViolation(
                    scenario_id="static-contract",
                    regret=float(len(static.violations)),
                    what=f"{len(static.violations)} static contract violations",
                )
            )
        if result.ood_score is None or (
            not soft_penalty and result.ood_score > env.ood_threshold
        ):
            score = result.ood_score
            excess = (
                1.0
                if score is None
                else max(0.0, float(score) - env.ood_threshold)
            )
            violations.append(
                ScenarioViolation(
                    scenario_id="surrogate-domain",
                    regret=excess,
                    what=(
                        "OOD score was not computed"
                        if score is None
                        else f"OOD score {score:.6g} > {env.ood_threshold:.6g}"
                    ),
                )
            )
        calls["n"] += 1
        cards.append(
            candidate_card(
                schedule_hash=result.schedule_hash,
                theta=dict(theta.values),
                npv_predicted=npv if math.isfinite(npv) else None,
                npv_parts=result.npv_parts,
                ood_score=result.ood_score,
                ood_worst=result.ood_worst,
                scenario_ood=scenario_ood_threshold,
                physics=result.physics,
                static_violations=len(static.violations),
                dynamic_blocking_violations=None,
                feasible=not violations,
                violations=[
                    {
                        "scenario_id": item.scenario_id,
                        "regret": item.regret,
                        "what": item.what,
                    }
                    for item in violations
                ],
                strategy="cma-es",
                ood_exceedances=getattr(evaluator, "ood_exceedances", ()) or (),
            )
        )
        if npv > calls["best"]:
            calls["best"] = npv
            logger.info(
                f"  evaluation {calls['n']:3d}: new maximum {npv / 1e9:.3f} bln",
            )
        return OptimizerResult(
            objective=npv,
            feasible=not violations,
            violations_by_scenario=tuple(violations),
            provenance=provenance,
        )

    logger.info(
        f"CMA-ES: 10 parameters, budget {budget} evaluations, fixed-point cap "
        f"in search {search_cap}, seed {SEED}",
    )
    started = time.monotonic()
    report = optimize(
        objective, search_start, seed=seed, max_evaluations=budget
    )
    elapsed = time.monotonic() - started
    logger.info(
        f"search finished in {elapsed / 60:.1f} min, evaluations {report.evaluations}, "
        f"generations {report.generations}, stop: {report.stop_reason}, "
        f"feasible found: {report.feasible_found}",
    )
    _write_diagnostics_head(
        seed=SEED,
        budget=budget,
        search_cap=search_cap,
        final_cap=final_cap,
        env=env,
        threshold_decision=threshold_decision,
        soft_penalty=soft_penalty,
        penalty_rate=penalty_rate,
        bhp_tolerance=bhp_tolerance,
        history=report.history,
        cards=cards,
        registry=registry,
        path=SEARCH_DIAGNOSTICS,
    )

    ranked = sorted(
        report.feasible_history,
        key=lambda item: item.result.objective,
        reverse=True,
    )
    if not ranked:
        return _search_near_baseline(env, evaluator, budget, provenance, registry)

    finalists, finalist_cards = evaluate_finalists(
        ranked,
        env=env,
        evaluator=evaluator,
        final_evaluator=final_evaluator,
        initial=initial,
        final_cap=final_cap,
        bhp_tolerance=bhp_tolerance,
        soft_penalty=soft_penalty,
        scenario_ood_threshold=scenario_ood_threshold,
        registry=registry,
    )
    _write_diagnostics_tail(finalist_cards, registry, SEARCH_DIAGNOSTICS)
    if not finalists:
        return _search_near_baseline(env, evaluator, budget, provenance, registry)

    (
        predicted_npv,
        best_theta,
        schedule,
        final,
        check,
        surrogate_blocking,
        schedule_hash,
        predicted_sigma,
    ) = select_finalist(finalists, RISK_AVERSION_BETA)
    delta = 100.0 * (predicted_npv - BASE_NPV) / BASE_NPV
    logger.info(
        f"\nθ*: NPV {predicted_npv / 1e9:.3f} bln ({delta:+.1f}% vs baseline), "
        f"validate_static violations: {len(check.violations)}, "
        f"blocking surrogate validate_dynamic: {len(surrogate_blocking)}, "
        f"events {check.n_control_events}, "
        f"converged: {final.converged}, self-consistent: {final.self_consistent}",
    )
    logger.info(f"canonical_schedule_hash: {schedule_hash}")

    run_budget = close_run_clock(report.evaluations)
    return SearchOutcome(
        schedule=schedule,
        theta=best_theta,
        predicted_npv=predicted_npv,
        schedule_hash=schedule_hash,
        provenance=dict(
            provenance,
            search_strategy="cma-es",
            selected_candidate="finalist",
            risk_aversion_beta=str(RISK_AVERSION_BETA),
            npv_sigma=(
                "none" if predicted_sigma is None else repr(float(predicted_sigma))
            ),
            policy_equilibrium=(
                "reached" if final.self_consistent else "not-claimed"
            ),
            **run_budget.as_provenance(),
        ),
        evaluations=report.evaluations,
        converged=final.converged,
        self_consistent=final.self_consistent,
        static_violations=len(check.violations),
        dynamic_blocking_violations=len(surrogate_blocking),
        incumbent_history=registry.records,
        budget=run_budget,
    )
