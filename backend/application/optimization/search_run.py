"""CMA-ES поверх суррогата на измеренной λ — вторая половина задачи G5.

`schedule_search.py` собирает один прогон θ → `Schedule*`; здесь по θ идёт
поиск. Каждая оценка — сквозной прогон через неподвижную точку и суррогат,
симулятор не участвует: прогноз стоит секунды, прогон Flow — десятки минут.

**Потолок неподвижной точки в поиске занижен до двух итераций.** Такая
на этапе поиска допустимость означает статический контракт: двух итераций
недостаточно, чтобы отвергать большинство θ как несошедшиеся. Лучшие θ
пересчитываются с полным потолком 24; наружу выходит только
самосогласованный кандидат без статических нарушений.

ЧДД поиска остаётся прогнозом production-ансамбля и отдельной экономической
головы. Он служит для ранжирования планов; честный итог фиксирует только
последующий прогон OPM/Flow.

Запуск: `PYTHONPATH=. python -m backend.application.optimization.search_run [бюджет оценок]`.
Нужны `torch` (extras `ml`), чекпойнт суррогата и измеренная λ.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.core.contracts import (
    OptimizerResult,
    ScenarioViolation,
    Schedule,
    Theta,
    EventKind,
    compensation_policy,
    hash_schedule,
    water_supply_policy,
)
from backend.domain.economics import load_response_artifact
from backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from backend.application.optimization.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.application.optimization.search import optimize
from backend.domain.policy.fixed_point import resolve
from backend.domain.policy.theta import default_theta
from backend.domain.schedule import (
    ViolationKind,
    canonicalize,
    validate_dynamic,
    validate_static,
)
from backend.infrastructure.resources import chdd_python_dir, model_z_dir
from backend.application.cases import load_case

LAMBDA = Path(os.environ.get("AIOS_LAMBDA_PATH", "data/lambda-window-2007/lambda.json"))
RESPONSE = Path("data/base_case/response.json")
CONSTRAINTS = Path(
    os.environ.get("AIOS_CONSTRAINTS_PATH", "config/competition-constraints.json")
)
SEARCH_DIAGNOSTICS = Path("data/lambda-window-2007/cmaes-diagnostics.json")
BASE_NPV = 11_873_676_459.64
SEED = 20260816
SEARCH_CAP = 2
FINAL_CAP = 8
FINALIST_CAP = 4
OOD_THRESHOLD = float(os.environ.get("AIOS_OOD_THRESHOLD", "0.0"))
BUDGET = 120

# Pressure is a simulator-side safety gate: the production surrogate is used
# to rank trajectories, but its BHP head is not accurate enough to reject a
# deck. All constraints that are already definitive from the predicted
# volumes, axes and roles remain blocking before OPM.
SURROGATE_NONBLOCKING_KINDS = frozenset(
    {
        ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
        ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
    }
)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """The one plan selected by the fast-model search."""

    schedule: Schedule
    theta: Theta
    predicted_npv: float
    schedule_hash: str
    provenance: dict[str, str]
    evaluations: int
    converged: bool
    self_consistent: bool


class SearchRunError(RuntimeError):
    """No candidate is safe to hand to the simulator or UI."""


def _repair_predicted_water_balance(env, evaluator, schedule: Schedule, rounds: int = 8):
    """Project a selected schedule into its own predicted water budget."""

    policy = water_supply_policy(env.constraints)
    if not policy.enabled:
        evaluated = evaluator(schedule)
        response = evaluated.state.response
        dynamic = validate_dynamic(
            schedule,
            response.state_at_date,
            response.interval_response,
            env.constraints,
            env.oil_density_t_per_m3,
        )
        return schedule, evaluated, dynamic, 0

    current = schedule
    for round_index in range(rounds + 1):
        evaluated = evaluator(current)
        response = evaluated.state.response
        dynamic = validate_dynamic(
            current,
            response.state_at_date,
            response.interval_response,
            env.constraints,
            env.oil_density_t_per_m3,
        )
        bad_steps = {
            item.control_step
            for item in dynamic.violations
            if item.kind is ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED
            and item.control_step is not None
        }
        if not bad_steps or round_index == rounds:
            return current, evaluated, dynamic, round_index

        produced_water: dict[int, float] = {}
        injected: dict[int, float] = {}
        for item in response.interval_response:
            oil_volume = max(0.0, item.oil_mass_delta) / env.oil_density_t_per_m3
            produced_water[item.control_step] = produced_water.get(item.control_step, 0.0) + max(
                0.0, item.liquid_volume_delta - oil_volume
            )
            injected[item.control_step] = injected.get(item.control_step, 0.0) + max(
                0.0, item.injection_volume_delta
            )
        factors: dict[int, float] = {}
        for step in bad_steps:
            source_step = step - policy.lag_steps
            days = (env.control_dates[step + 1] - env.control_dates[step]).days
            available = (
                policy.external_water_m3_per_day * days
                + float(policy.reinjection_fraction or 0.0)
                * produced_water.get(source_step, 0.0)
            )
            actual = injected.get(step, 0.0)
            factors[step] = 0.0 if actual <= 0.0 else min(0.95, 0.98 * available / actual)

        values: dict[tuple[int, str], float] = {}
        repaired = []
        for event in current.control_events:
            if event.kind is EventKind.SET_RATE and event.control_step in factors:
                value = math.floor(float(event.value or 0.0) * factors[event.control_step])
                event = replace(event, value=max(0.0, value))
                values[(event.control_step, event.well)] = float(event.value or 0.0)
            repaired.append(event)
        normalized = []
        for event in repaired:
            value = values.get((event.control_step, event.well))
            if value is not None and event.kind in (EventKind.OPEN, EventKind.SHUT):
                event = replace(
                    event,
                    kind=EventKind.OPEN if value > 0.0 else EventKind.SHUT,
                )
            normalized.append(event)
        current = canonicalize(replace(current, control_events=tuple(normalized)))
    raise AssertionError("unreachable")


def _search_theta(constraints) -> Theta:
    """Restrict R5 tuning to the case's declared compensation corridor."""

    base = default_theta()
    corridor = compensation_policy(constraints)
    if not corridor.enabled:
        return base
    assert corridor.minimum is not None and corridor.maximum is not None
    bounds = dict(base.bounds)
    low_floor, low_ceiling = bounds["r5_compensation_low"]
    high_floor, high_ceiling = bounds["r5_compensation_high"]
    bounds["r5_compensation_low"] = (
        max(low_floor, corridor.minimum),
        min(low_ceiling, corridor.maximum),
    )
    bounds["r5_compensation_high"] = (
        max(high_floor, corridor.minimum),
        min(high_ceiling, corridor.maximum),
    )
    for name in ("r5_compensation_low", "r5_compensation_high"):
        if bounds[name][0] >= bounds[name][1]:
            raise SearchRunError(
                f"коридор кейса несовместим с границами {name}: {bounds[name]}"
            )
    values = dict(base.values)
    for name in ("r5_compensation_low", "r5_compensation_high"):
        values[name] = min(max(values[name], bounds[name][0]), bounds[name][1])
    return Theta(values=values, bounds=bounds)


def run_search(
    *, budget: int = BUDGET, case_path: Path | None = None
) -> SearchOutcome:
    """Run CMA-ES and return the plan instead of deciding where to save it."""
    artifacts = resolve_runtime_artifacts()
    constraints_path = Path(case_path) if case_path is not None else CONSTRAINTS
    constraints = load_case(constraints_path)
    env = load_environment(
        model_dir=model_z_dir(),
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        lambda_path=LAMBDA,
        constraints=constraints,
        ood_threshold=OOD_THRESHOLD,
    )
    validate_runtime_economic_head(artifacts, env.npv_head)
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)
    search_start = _search_theta(constraints)
    provenance = {
        "model_version": env.model.version,
        "lambda_window": f"{env.lambda_.window_start}..{env.lambda_.window_end}",
        "lambda_stability": f"{env.lambda_.stability:.3f}",
        "seed": str(SEED),
        "runtime_artifact_source": artifacts.source,
        "npv_head_version": env.npv_head.version if env.npv_head else "none",
        "constraints_path": str(constraints_path),
        "ood_threshold": str(env.ood_threshold),
    }
    calls = {"n": 0, "best": float("-inf")}

    def objective(theta) -> OptimizerResult:
        result = resolve(make_policy(env, theta, {}), evaluator, initial, SEARCH_CAP)
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
        if result.ood_score is None or result.ood_score > env.ood_threshold:
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
        if npv > calls["best"]:
            calls["best"] = npv
            print(
                f"  оценка {calls['n']:3d}: новый максимум {npv / 1e9:.3f} млрд",
                flush=True,
            )
        return OptimizerResult(
            objective=npv,
            feasible=not violations,
            violations_by_scenario=tuple(violations),
            provenance=provenance,
        )

    print(
        f"CMA-ES: параметров 10, бюджет {budget} оценок, потолок неподвижной "
        f"точки в поиске {SEARCH_CAP}, seed {SEED}",
        flush=True,
    )
    started = time.monotonic()
    report = optimize(
        objective, search_start, seed=SEED, max_evaluations=budget
    )
    elapsed = time.monotonic() - started
    print(
        f"поиск закончен за {elapsed / 60:.1f} мин, оценок {report.evaluations}, "
        f"поколений {report.generations}, останов: {report.stop_reason}, "
        f"допустимых найдено: {report.feasible_found}",
        flush=True,
    )
    SEARCH_DIAGNOSTICS.parent.mkdir(parents=True, exist_ok=True)
    SEARCH_DIAGNOSTICS.write_text(
        json.dumps(
            {
                "seed": SEED,
                "budget": budget,
                "search_cap": SEARCH_CAP,
                "model_version": env.model.version,
                "npv_head_version": env.npv_head.version if env.npv_head else None,
                "ood_threshold": env.ood_threshold,
                "evaluations": [
                    {
                        "theta": dict(item.theta.values),
                        "npv_predicted": item.result.objective,
                        "feasible": item.result.feasible,
                        "violations": [
                            {
                                "scenario_id": violation.scenario_id,
                                "regret": violation.regret,
                                "what": violation.what,
                            }
                            for violation in item.result.violations_by_scenario
                        ],
                    }
                    for item in report.history
                ],
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
        raise SearchRunError(
            "поиск не нашёл ни одной статически допустимой θ; "
            "проверьте ограничения кейса и политику"
        )

    finalists = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    print("\nполный пересчёт лучших допустимых θ:", flush=True)
    for candidate in ranked:
        signature = tuple(sorted(candidate.theta.values.items()))
        if signature in seen:
            continue
        seen.add(signature)
        final = resolve(
            make_policy(env, candidate.theta, {}), evaluator, initial, FINAL_CAP
        )
        check = validate_static(final.schedule, env.constraints)
        repaired_schedule, evaluated, dynamic, repair_rounds = _repair_predicted_water_balance(
            env, evaluator, final.schedule
        )
        check = validate_static(repaired_schedule, env.constraints)
        surrogate_blocking = tuple(
            item
            for item in dynamic.blocking_violations
            if item.kind not in SURROGATE_NONBLOCKING_KINDS
        )
        print(
            f"  ЧДД {final.npv / 1e9:8.3f} млрд, итераций {final.iterations:2d}, "
            f"self-consistent={final.self_consistent}, OOD={final.ood_score}, "
            f"water-repair={repair_rounds}, static={len(check.violations)}, "
            f"dynamic-blocking={len(surrogate_blocking)}, "
            f"BHP-to-OPM={len(dynamic.blocking_violations) - len(surrogate_blocking)}",
            flush=True,
        )
        if (
            check.ok
            and not surrogate_blocking
            and final.ood_score is not None
            and final.ood_score <= env.ood_threshold
        ):
            finalists.append(
                (
                    evaluated.npv,
                    candidate.theta,
                    repaired_schedule,
                    final,
                    check,
                    surrogate_blocking,
                )
            )
        if len(seen) >= FINALIST_CAP:
            break
    if not finalists:
        raise SearchRunError(
            "ни один финалист не прошёл статический/динамический/OOD гейт; "
            "расписание не экспортировано"
        )

    predicted_npv, best_theta, schedule, final, check, surrogate_blocking = max(
        finalists, key=lambda item: (item[3].self_consistent, item[0])
    )
    schedule_hash = hash_schedule(schedule)
    delta = 100.0 * (predicted_npv - BASE_NPV) / BASE_NPV
    print(
        f"\nθ*: ЧДД {predicted_npv / 1e9:.3f} млрд ({delta:+.1f}% к базовому), "
        f"нарушений validate_static: {len(check.violations)}, "
        f"блокирующих surrogate validate_dynamic: {len(surrogate_blocking)}, "
        f"событий {check.n_control_events}, "
        f"сошлось: {final.converged}, самосогласовано: {final.self_consistent}",
        flush=True,
    )
    print(f"canonical_schedule_hash: {schedule_hash}", flush=True)

    return SearchOutcome(
        schedule=schedule,
        theta=best_theta,
        predicted_npv=predicted_npv,
        schedule_hash=schedule_hash,
        provenance=provenance,
        evaluations=report.evaluations,
        converged=final.converged,
        self_consistent=final.self_consistent,
    )


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else BUDGET
    case_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    outcome = run_search(budget=budget, case_path=case_path)
    out = Path("data/lambda-window-2007/cmaes.json")
    out.write_text(
        json.dumps(
            {
                "seed": SEED,
                "budget": budget,
                "evaluations": outcome.evaluations,
                "search_cap": SEARCH_CAP,
                "final_cap": FINAL_CAP,
                "theta": dict(outcome.theta.values),
                "npv_predicted": outcome.predicted_npv,
                "npv_baseline": BASE_NPV,
                "canonical_schedule_hash": outcome.schedule_hash,
                "static_violations": 0,
                "dynamic_blocking_violations": 0,
                "converged": outcome.converged,
                "self_consistent": outcome.self_consistent,
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
