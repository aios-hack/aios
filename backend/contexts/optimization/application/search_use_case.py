from __future__ import annotations

import logging

from backend.contexts.optimization.application.baseline_search import (
    _peak_step_production,
)
from backend.contexts.optimization.domain.gates.bhp_tolerance import (
    BHP_KINDS,
    DEFAULT_SURROGATE_METRICS,
    SURROGATE_NONBLOCKING_KINDS,
)
from backend.contexts.optimization.domain.gates.incumbent import (
    IncumbentRecord,
)
from backend.contexts.optimization.domain.gates.ood_threshold import (
    CONSERVATIVE_OOD_THRESHOLD,
    DEFAULT_OOD_CALIBRATION,
    OOD_CALIBRATION_FORMAT,
    OodThreshold,
)
from backend.contexts.optimization.domain.gates.opm_budget import (
    OPM_BUDGET_JOURNAL,
    RUN_CLOCK,
    measure_run_budget,
)
from backend.contexts.optimization.domain.search_limits import (
    DEFAULT_FINAL_CAP,
    DEFAULT_SEARCH_CAP,
    INJECTION_TRANSFER_STEPS_M3_PER_DAY,
    WATER_REPAIR_CEILING,
    WATER_REPAIR_MARGIN,
)
from backend.contexts.optimization.domain.selection import (
    _risk_adjusted_npv,
)

from backend.contexts.optimization.domain.errors import (
    BhpToleranceError,
    ConnectivitySearchError,
    OpmBudgetError,
)
from backend.contexts.optimization.domain.gates.bhp_tolerance import (
    BhpTolerance,
    SURROGATE_METRICS_FORMAT,
    bhp_exceedance_bar,
)
from backend.contexts.optimization.domain.gates.opm_budget import (
    RunBudget,
    read_opm_budget,
)
from backend.contexts.optimization.domain.injection_transfer import (
    _baseline_injection_rates,
    _connectivity_groups,
    _injection_transfer_plan,
    _lambda_connectivity,
    _transfer_injection,
)
from backend.contexts.optimization.domain.search_limits import (
    MISSING_SIGMA,
)

from backend.contexts.optimization.application.baseline_search import (
    _search_near_baseline,
    _search_theta,
)

from backend.contexts.optimization.application.water_repair import (
    _repair_predicted_water_balance,
)

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

from backend.contexts.optimization.infrastructure.diagnostics_journal import (
    _evaluation_cards,
    _write_diagnostics_tail,
    candidate_card,
)


from backend.contexts.optimization.domain.selection import (
    SearchOutcome,
    select_finalist,
)

from backend.contexts.optimization.domain.gates.opm_budget import (
    close_run_clock,
    start_run_clock,
)

from backend.contexts.optimization.domain.gates.incumbent import (
    FINALIST_CAP,
    IncumbentRegistry,
    _physics_admissible,
    incumbent_gate_passed,
)

from backend.contexts.optimization.domain.gates.bhp_tolerance import (
    _bhp_tolerance_decision,
    surrogate_blocking_violations,
)

from backend.contexts.optimization.domain.gates.ood_threshold import (
    _ood_threshold_decision,
    _soft_penalty_enabled,
    _soft_penalty_rate,
)

from backend.contexts.optimization.domain.errors import (
    SearchRunError,
)

import json
import math
import sys
import time
from dataclasses import (
    replace,
)
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.core.contracts import (
    OptimizerResult,
    ScenarioViolation,
    hash_schedule,
    canonical_bytes,
)
from backend.domain.economics import load_response_artifact
from backend.contexts.optimization.application.environment import (
    OutOfDomainScheduleError,
    PhysicallyImpossibleScheduleError,
    load_environment,
    make_evaluator,
)
from backend.contexts.optimization.application.policy_factory import (
    make_policy,
)
from backend.contexts.optimization.infrastructure.artifacts import (
    resolve_lambda_selection,
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.contexts.optimization.domain.optimizer import optimize
from backend.contexts.policy.domain.fixed_point import (
    resolve,
)
from backend.domain.schedule import (
    validate_static,
)
from backend.shared.resources import chdd_python_dir, model_z_dir
from backend.contexts.constraints.application.cases import load_case
from backend.contexts.constraints.infrastructure.constraints_io import constraints_hash

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
            f"потолок неподвижной точки должен быть положительным: "
            f"поиск {search_cap}, финал {final_cap}"
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
    provenance = {
        "model_version": env.model.version,
        "lambda_window": f"{env.lambda_.window_start}..{env.lambda_.window_end}",
        "lambda_stability": f"{env.lambda_.stability:.3f}",
        "seed": str(seed),
        "runtime_artifact_source": artifacts.source,
        "feature_context_sha256": _artifact_sha256(
            artifacts.feature_context, "feature_context"
        ),
        "constraints_hash": constraints_hash(constraints),
        "scenario_ood_version": env.scenario_ood.version if env.scenario_ood else "none",
        "npv_head_version": env.npv_head.version if env.npv_head else "none",
        "constraints_path": str(constraints_path),
        **lambda_selection.as_provenance(),
        **threshold_decision.as_provenance(),
        **bhp_tolerance.as_provenance(),
        "ood_soft_penalty": "true" if soft_penalty else "false",
        "ood_penalty_per_unit": repr(penalty_rate),
        "search_fixed_point_cap": str(search_cap),
        "final_fixed_point_cap": str(final_cap),
        "search_strategy": "cma-es",
        "policy_equilibrium": "not-claimed",
    }
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
                    what=f"{len(static.violations)} нарушений статического контракта",
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
                        "OOD score не вычислен"
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
                f"  оценка {calls['n']:3d}: новый максимум {npv / 1e9:.3f} млрд",
            )
        return OptimizerResult(
            objective=npv,
            feasible=not violations,
            violations_by_scenario=tuple(violations),
            provenance=provenance,
        )

    logger.info(
        f"CMA-ES: параметров 10, бюджет {budget} оценок, потолок неподвижной "
        f"точки в поиске {search_cap}, seed {SEED}",
    )
    started = time.monotonic()
    report = optimize(
        objective, search_start, seed=seed, max_evaluations=budget
    )
    elapsed = time.monotonic() - started
    logger.info(
        f"поиск закончен за {elapsed / 60:.1f} мин, оценок {report.evaluations}, "
        f"поколений {report.generations}, останов: {report.stop_reason}, "
        f"допустимых найдено: {report.feasible_found}",
    )
    SEARCH_DIAGNOSTICS.parent.mkdir(parents=True, exist_ok=True)
    SEARCH_DIAGNOSTICS.write_text(
        json.dumps(
            {
                "seed": SEED,
                "budget": budget,
                "search_cap": search_cap,
                "final_cap": final_cap,
                "model_version": env.model.version,
                "npv_head_version": env.npv_head.version if env.npv_head else None,
                "ood_threshold": env.ood_threshold,
                "ood_threshold_origin": threshold_decision.origin,
                "ood_threshold_calibrated": threshold_decision.calibrated,
                "ood_soft_penalty": soft_penalty,
                "ood_penalty_per_unit": penalty_rate,
                "bhp_gate_delta_bar": bhp_tolerance.delta_bar,
                "bhp_gate_delta_origin": bhp_tolerance.origin,
                "bhp_gate_delta_detail": bhp_tolerance.detail,
                "evaluations": _evaluation_cards(report.history, cards),
                "incumbents": registry.as_list(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    ranked = sorted(
        report.feasible_history,
        key=lambda item: item.result.objective,
        reverse=True,
    )
    if not ranked:
        return _search_near_baseline(env, evaluator, budget, provenance, registry)

    finalists = []
    finalist_cards: list[dict[str, object]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    logger.info("\nполный пересчёт лучших допустимых θ:")
    for candidate in ranked:
        signature = tuple(sorted(candidate.theta.values.items()))
        if signature in seen:
            continue
        seen.add(signature)
        try:
            final = resolve(
                make_policy(env, candidate.theta, {}), evaluator, initial, final_cap
            )
            check = validate_static(final.schedule, env.constraints)
            repaired_schedule, evaluated, dynamic, repair_rounds = _repair_predicted_water_balance(
                env, final_evaluator, final.schedule
            )
            check = validate_static(repaired_schedule, env.constraints)
        except (OutOfDomainScheduleError, PhysicallyImpossibleScheduleError) as error:
            logger.info(f"  finalist rejected: {error}")
            continue
        surrogate_blocking = surrogate_blocking_violations(
            dynamic.blocking_violations, env.constraints, bhp_tolerance
        )
        repaired_hash = hash_schedule(repaired_schedule)
        finalist_exceedances = tuple(
            getattr(final_evaluator, "ood_exceedances", ()) or ()
        )
        admissible = _physics_admissible(evaluated.physics)
        passed = incumbent_gate_passed(
            static_violations=len(check.violations),
            dynamic_blocking_violations=len(surrogate_blocking),
            ood_score=evaluated.ood_score,
            ood_threshold=env.ood_threshold,
            physics_admissible=admissible,
            ood_soft_penalty=soft_penalty,
        )
        finalist_cards.append(
            candidate_card(
                schedule_hash=repaired_hash,
                theta=dict(candidate.theta.values),
                npv_predicted=evaluated.npv,
                npv_parts=evaluated.npv_parts,
                ood_score=evaluated.ood_score,
                ood_worst=evaluated.ood_worst,
                scenario_ood=scenario_ood_threshold,
                physics=evaluated.physics,
                static_violations=len(check.violations),
                dynamic_blocking_violations=len(surrogate_blocking),
                feasible=passed,
                violations=[],
                strategy="finalist",
                ood_exceedances=finalist_exceedances,
            )
        )
        logger.info(
            f"  ЧДД {final.npv / 1e9:8.3f} млрд, итераций {final.iterations:2d}, "
            f"self-consistent={final.self_consistent}, OOD={evaluated.ood_score}, "
            f"water-repair={repair_rounds}, static={len(check.violations)}, "
            f"dynamic-blocking={len(surrogate_blocking)}, "
            f"physics-admissible={admissible}, "
            f"BHP-to-OPM={len(dynamic.blocking_violations) - len(surrogate_blocking)}",
        )
        if passed:
            finalists.append(
                (
                    evaluated.npv,
                    candidate.theta,
                    repaired_schedule,
                    final,
                    check,
                    surrogate_blocking,
                    repaired_hash,
                    evaluated.sigma,
                )
            )
            best = registry.current
            if best is None or evaluated.npv > best.npv_predicted:
                registry.promote(
                    stage="finalist",
                    schedule_hash=repaired_hash,
                    npv_predicted=evaluated.npv,
                    theta=dict(candidate.theta.values),
                    ood_score=evaluated.ood_score,
                    ood_worst=evaluated.ood_worst,
                    static_violations=len(check.violations),
                    dynamic_blocking_violations=len(surrogate_blocking),
                    physics_admissible=admissible,
                    self_consistent=final.self_consistent,
                    ood_exceedances=finalist_exceedances,
                )
        if len(seen) >= FINALIST_CAP:
            break
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
        f"\nθ*: ЧДД {predicted_npv / 1e9:.3f} млрд ({delta:+.1f}% к базовому), "
        f"нарушений validate_static: {len(check.violations)}, "
        f"блокирующих surrogate validate_dynamic: {len(surrogate_blocking)}, "
        f"событий {check.n_control_events}, "
        f"сошлось: {final.converged}, самосогласовано: {final.self_consistent}",
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


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else BUDGET
    case_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    outcome = run_search(budget=budget, case_path=case_path)
    out = SEARCH_RESULT
    schedule_path = out.with_name('cmaes-schedule.json')
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path.write_bytes(canonical_bytes(outcome.schedule))
    out.write_text(
        json.dumps(
            {
                "seed": SEED,
                "schedule_path": str(schedule_path),
                "budget": budget,
                "evaluations": outcome.evaluations,
                "search_cap": int(
                    outcome.provenance.get("search_fixed_point_cap", SEARCH_CAP)
                ),
                "final_cap": int(
                    outcome.provenance.get("final_fixed_point_cap", FINAL_CAP)
                ),
                "theta": dict(outcome.theta.values),
                "npv_predicted": outcome.predicted_npv,
                "npv_baseline": BASE_NPV,
                "canonical_schedule_hash": outcome.schedule_hash,
                "static_violations": outcome.static_violations,
                "dynamic_blocking_violations": outcome.dynamic_blocking_violations,
                "converged": outcome.converged,
                "self_consistent": outcome.self_consistent,
                "incumbents": [
                    record.as_dict() for record in outcome.incumbent_history
                ],
                **(
                    {
                        "wallclock_seconds": None,
                        "surrogate_evaluations": None,
                        "opm_runs": None,
                        "opm_runs_source": None,
                        "opm_wallclock_seconds": None,
                    }
                    if getattr(outcome, "budget", None) is None
                    else outcome.budget.as_dict()
                ),
                "provenance": outcome.provenance,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"итог записан: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
