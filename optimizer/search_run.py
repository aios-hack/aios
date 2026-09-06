"""CMA-ES поверх суррогата на измеренной λ — вторая половина задачи G5.

`schedule_search.py` собирает один прогон θ → `Schedule*`; здесь по θ идёт
поиск. Каждая оценка — сквозной прогон через неподвижную точку и суррогат,
симулятор не участвует: прогноз стоит секунды, прогон Flow — десятки минут.

**Потолок неподвижной точки в поиске занижен до двух итераций.** Полный
потолок стоит вдвое дороже за оценку, а порядок θ по ЧДД сохраняет: лучшая
θ в конце всё равно пересчитывается полным потолком, и в отчёт идёт это
число, а не поисковое. Приёмка — статический и динамический гейт на
фактическом отклике суррогата, включая баланс доступной воды.

**Числу верить нельзя.** Direct NPV head улучшает shortlist, но адаптивный
поиск способен найти его ошибку. Поиск даёт план, а честный ЧДД — только
прогон OPM, задача G7.

Запуск: `PYTHONPATH=. python -m optimizer.search_run [бюджет оценок]`.
Нужны `torch` (extras `ml`), чекпойнт суррогата и измеренная λ.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from contracts import OptimizerResult, ResponseArtifact, ScenarioViolation
from contracts.hashing import canonical_bytes, hash_schedule
from economics import analyze_base_case, load_response_artifact
from optimizer.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from optimizer.schedule_search import (
    OutOfDomainScheduleError,
    candidate_constraint_violations,
    load_environment,
    make_evaluator,
    make_policy,
)
from optimizer.search import optimize
from policy.fixed_point import resolve
from policy.theta import default_theta
from schedule import validate_static
from ui.scenarios import constraints_to_json, load_constraints_file

LAMBDA = Path(os.environ.get("AIOS_LAMBDA_PATH", "data/lambda-window-2007/lambda.json"))
RESPONSE = Path(os.environ.get("AIOS_RESPONSE_PATH", "data/base_case/response.json"))
MODEL_DIR = Path(os.environ.get("AIOS_MODEL_DIR", "../docs-src/models/Model_Z"))
NORMATIVES = Path(
    os.environ.get(
        "AIOS_NORMATIVES_PATH",
        "../docs/models/CHDD_PYTHON/input/Нормативы_ЧДД.xlsx",
    )
)
SEED = int(os.environ.get("AIOS_SEED", "20260816"))
SEARCH_CAP = 2
FINAL_CAP = 24
BUDGET = int(os.environ.get("AIOS_SEARCH_BUDGET", "120"))
OOD_THRESHOLD = float(os.environ.get("AIOS_OOD_THRESHOLD", "0"))
CONSTRAINTS_PATH = Path(
    os.environ.get("AIOS_CONSTRAINTS_PATH", "config/competition-constraints.json")
)
SEARCH_OUTPUT = Path(
    os.environ.get("AIOS_SEARCH_OUTPUT", "data/lambda-window-2007/cmaes.json")
)


def _load_case_constraints(path: Path):
    return load_constraints_file(path, require_water_supply=True)


def _scenario_violations(violations) -> tuple[ScenarioViolation, ...]:
    return tuple(
        ScenarioViolation(
            scenario_id=(
                f"nominal:{item.kind.value}:{item.control_step}:"
                f"{item.well or 'FIELD'}:{index}"
            ),
            regret=0.0,
            what=str(item),
        )
        for index, item in enumerate(violations)
    )


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else BUDGET
    out = SEARCH_OUTPUT
    out.parent.mkdir(parents=True, exist_ok=True)
    constraints = _load_case_constraints(CONSTRAINTS_PATH)
    constraints_document = constraints_to_json(constraints)
    constraints_hash = hashlib.sha256(
        canonical_bytes(constraints_document)
    ).hexdigest()
    artifacts = resolve_runtime_artifacts()
    env = load_environment(
        model_dir=MODEL_DIR,
        normatives_path=NORMATIVES,
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        lambda_path=LAMBDA,
        ood_threshold=OOD_THRESHOLD,
        constraints=constraints,
    )
    validate_runtime_economic_head(artifacts, env.npv_head)
    initial = load_response_artifact(RESPONSE)
    baseline_npv = analyze_base_case(
        initial,
        env.deck_dates,
        env.t0_deck_date_index,
        env.normatives,
        env.policies,
    ).npv_methodology
    baseline_violations = candidate_constraint_violations(
        env, env.base_schedule, initial
    )
    evaluator = make_evaluator(env)
    # Суррогатная оценка самого эталона. Сравнивать ЧДД кандидата (суррогат) с
    # `baseline_npv` (настоящий OPM) нельзя — это разные источники, и разница
    # между ними спрячет разницу между расписаниями. Для допуска кандидата к
    # дорогому прогону сравнение обязано идти в одних единицах.
    baseline_surrogate_npv = evaluator(env.base_schedule).npv
    provenance = {
        "model_version": env.model.version,
        "lambda_window": f"{env.lambda_.window_start}..{env.lambda_.window_end}",
        "lambda_stability": f"{env.lambda_.stability:.3f}",
        "seed": str(SEED),
        "ood_threshold": str(OOD_THRESHOLD),
        "npv_calibrated": str(env.npv_calibration is not None).lower(),
        "npv_head_version": (
            env.npv_head.version if env.npv_head is not None else "none"
        ),
        "runtime_artifact_source": artifacts.source,
        "checkpoint_path": str(artifacts.checkpoint),
        "feature_context_path": str(artifacts.feature_context),
        "npv_head_path": str(artifacts.npv_head),
        "baseline_response_hash": initial.response_hash,
        "constraints_path": str(CONSTRAINTS_PATH),
        "constraints_hash": constraints_hash,
        "baseline_constraint_violations": str(len(baseline_violations)),
        "baseline_surrogate_npv_rub": f"{baseline_surrogate_npv:.6f}",
        "surrogate_water_balance_trusted": "false",
    }
    calls = {"n": 0, "best": float("-inf")}

    def objective(theta) -> OptimizerResult:
        try:
            result = resolve(
                make_policy(env, theta, {}), evaluator, initial, SEARCH_CAP
            )
        except OutOfDomainScheduleError as error:
            calls["n"] += 1
            return OptimizerResult(
                objective=-1.0e30,
                feasible=False,
                violations_by_scenario=(
                    ScenarioViolation(
                        scenario_id="nominal:ood",
                        regret=0.0,
                        what=str(error),
                    ),
                ),
                provenance=provenance,
            )
        evaluation = evaluator(result.schedule)
        if not isinstance(evaluation.state, ResponseArtifact):
            raise TypeError("оценщик кандидата вернул не ResponseArtifact")
        violations = candidate_constraint_violations(
            env,
            result.schedule,
            evaluation.state,
            trust_surrogate_water_balance=False,
        )
        npv = evaluation.npv
        calls["n"] += 1
        feasible = not violations
        if feasible and npv > calls["best"]:
            calls["best"] = npv
            print(
                f"  оценка {calls['n']:3d}: новый максимум {npv / 1e9:.3f} млрд",
                flush=True,
            )
        return OptimizerResult(
            objective=npv,
            feasible=feasible,
            violations_by_scenario=_scenario_violations(violations),
            provenance=provenance,
        )

    print(
        f"CMA-ES: параметров 10, бюджет {budget} оценок, потолок неподвижной "
        f"точки в поиске {SEARCH_CAP}, seed {SEED}",
        flush=True,
    )
    if baseline_violations:
        print(
            f"ВНИМАНИЕ: прежний базовый отклик имеет "
            f"{len(baseline_violations)} нарушений нового кейса; его ЧДД "
            "сохраняется только как unconstrained-диагностика и не является "
            "эталоном сравнения.",
            flush=True,
        )
    started = time.monotonic()
    report = optimize(
        objective, default_theta(), seed=SEED, max_evaluations=budget
    )
    elapsed = time.monotonic() - started
    print(
        f"поиск закончен за {elapsed / 60:.1f} мин, оценок {report.evaluations}, "
        f"поколений {report.generations}, останов: {report.stop_reason}, "
        f"допустимых найдено: {report.feasible_found}",
        flush=True,
    )

    if not report.feasible_found:
        print(
            "Поиск не нашёл ни одного допустимого кандидата; θ и ЧДД не "
            "публикуются как результат.",
            flush=True,
        )
        for violation in report.best.result.violations_by_scenario[:10]:
            print(f"  {violation.what}", flush=True)
        return 3

    best_theta = report.best.theta
    print("\nпересчёт лучшей θ полным потолком:", flush=True)
    final = resolve(make_policy(env, best_theta, {}), evaluator, initial, FINAL_CAP)
    for item in final.visited:
        print(f"  {item.iteration}: ЧДД {item.npv / 1e9:8.3f} млрд", flush=True)
    final_evaluation = evaluator(final.schedule)
    if not isinstance(final_evaluation.state, ResponseArtifact):
        raise TypeError("финальный оценщик вернул не ResponseArtifact")
    final_violations = candidate_constraint_violations(
        env,
        final.schedule,
        final_evaluation.state,
        trust_surrogate_water_balance=False,
    )
    check = validate_static(final.schedule, constraints)
    if not final.self_consistent:
        diagnostic = out.with_name("cmaes-unconverged.json")
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        diagnostic.write_text(
            json.dumps(
                {
                    "seed": SEED,
                    "budget": budget,
                    "theta": dict(best_theta.values),
                    "iterations": final.iterations,
                    "visited": [
                        {
                            "iteration": item.iteration,
                            "npv_predicted": item.npv,
                            "canonical_schedule_hash": item.schedule_hash,
                        }
                        for item in final.visited
                    ],
                    "constraints_hash": constraints_hash,
                    "valid_for_submission": False,
                    "reason": "fixed point is not self-consistent",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(
            f"\nФИНАЛЬНЫЙ КАНДИДАТ ОТКЛОНЁН: неподвижная точка не "
            f"самосогласована за {FINAL_CAP} итераций; диагностика {diagnostic}",
            flush=True,
        )
        return 5
    if final_violations:
        print(
            f"\nФИНАЛЬНЫЙ КАНДИДАТ ОТКЛОНЁН: "
            f"{len(final_violations)} нарушений; первое — {final_violations[0]}",
            flush=True,
        )
        return 4
    # Incumbent-гейт. Без него протокол способен обязательно выбрать
    # ухудшение: на G10 все 40 кандидатов были хуже эталона на 1.036 млрд, и
    # поиск всё равно вернул максимум прогноза. Сравнение идёт суррогат против
    # суррогата; фактическое сравнение делает submission-тракт после OPM.
    improvement = final_evaluation.npv - baseline_surrogate_npv
    if improvement <= 0.0:
        print(
            f"\nКАНДИДАТ НЕ БЬЁТ ЭТАЛОН: суррогатный ЧДД "
            f"{final_evaluation.npv / 1e9:.3f} против {baseline_surrogate_npv / 1e9:.3f} "
            f"млрд у эталона ({improvement / 1e6:+.1f} млн ₽). Сдаётся эталон: "
            "прогон OPM на заведомо худшем расписании стоит пятнадцать минут и "
            "ничего не даёт.",
            flush=True,
        )
        return 7

    comparison = " (без сравнения: старый baseline недопустим)"
    if not baseline_violations:
        delta = 100.0 * (final_evaluation.npv - baseline_npv) / baseline_npv
        comparison = f" ({delta:+.1f}% к допустимому базовому)"
    print(
        f"\nθ*: ЧДД {final_evaluation.npv / 1e9:.3f} млрд"
        f"{comparison}, "
        f"нарушений validate_static: {len(check.violations)}, "
        f"событий {check.n_control_events}, "
        f"сошлось: {final.converged}",
        flush=True,
    )
    print(
        f"canonical_schedule_hash: {hash_schedule(final.schedule)}", flush=True
    )

    out.write_text(
        json.dumps(
            {
                "seed": SEED,
                "budget": budget,
                "evaluations": report.evaluations,
                "search_cap": SEARCH_CAP,
                "final_cap": FINAL_CAP,
                "theta": dict(best_theta.values),
                "npv_predicted": final_evaluation.npv,
                "npv_baseline_unconstrained": baseline_npv,
                "baseline_constraint_violations": len(baseline_violations),
                "baseline_response_hash": initial.response_hash,
                "canonical_schedule_hash": hash_schedule(final.schedule),
                "static_violations": len(check.violations),
                "dynamic_constraint_violations": len(final_violations),
                "converged": final.converged,
                "self_consistent": final.self_consistent,
                "valid_for_submission": True,
                "constraints": constraints_document,
                "constraints_hash": constraints_hash,
                "provenance": provenance,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    schedule_out = out.with_name("cmaes-schedule.json")
    schedule_out.write_bytes(canonical_bytes(final.schedule))
    print(f"итог записан: {out}", flush=True)
    print(f"расписание записано: {schedule_out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
