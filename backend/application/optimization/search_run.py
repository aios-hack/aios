"""CMA-ES поверх суррогата на измеренной λ — вторая половина задачи G5.

`schedule_search.py` собирает один прогон θ → `Schedule*`; здесь по θ идёт
поиск. Каждая оценка — сквозной прогон через неподвижную точку и суррогат,
симулятор не участвует: прогноз стоит секунды, прогон Flow — десятки минут.

**Потолок неподвижной точки в поиске занижен до двух итераций.** Полный
потолок стоит вдвое дороже за оценку, а порядок θ по ЧДД сохраняет: лучшая
θ в конце всё равно пересчитывается полным потолком, и в отчёт идёт это
число, а не поисковое. Приёмка — `validate_static` на итоговом расписании.

**Числу верить нельзя.** Его даёт суррогат с `precision@1` равным нулю и
`regret@1` в 201 млн руб (`SURROGATE_HANDOFF.md` §6). Поиск даёт план, а
честный ЧДД — только прогон OPM, задача G7.

Запуск: `PYTHONPATH=. python -m backend.application.optimization.search_run [бюджет оценок]`.
Нужны `torch` (extras `ml`), чекпойнт суррогата и измеренная λ.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.core.contracts import OptimizerResult, Schedule, Theta
from backend.core.contracts.hashing import hash_schedule
from backend.domain.economics import load_response_artifact
from backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from backend.application.optimization.search import optimize
from backend.domain.policy.fixed_point import resolve
from backend.domain.policy.theta import default_theta
from backend.domain.schedule import validate_static
from backend.infrastructure.resources import chdd_python_dir, model_z_dir

DATASET = Path(os.environ.get("AIOS_CHECKPOINT_DIR", "../dataset-700/model-task34-700"))
LAMBDA = Path(os.environ.get("AIOS_LAMBDA_PATH", "data/lambda-window-2007/lambda.json"))
RESPONSE = Path("data/base_case/response.json")
BASE_NPV = 11_873_676_459.64
SEED = 20260816
SEARCH_CAP = 2
FINAL_CAP = 4
BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else 120


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """The one plan selected by the fast-model search."""

    schedule: Schedule
    theta: Theta
    predicted_npv: float
    schedule_hash: str
    provenance: dict[str, str]
    evaluations: int


def run_search(*, budget: int = BUDGET) -> SearchOutcome:
    """Run CMA-ES and return the plan instead of deciding where to save it."""
    env = load_environment(
        model_dir=model_z_dir(),
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=DATASET / "model.pt",
        feature_context_path=DATASET / "feature_context.json",
        lambda_path=LAMBDA,
    )
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)
    provenance = {
        "model_version": env.model.version,
        "lambda_window": f"{env.lambda_.window_start}..{env.lambda_.window_end}",
        "lambda_stability": f"{env.lambda_.stability:.3f}",
        "seed": str(SEED),
    }
    calls = {"n": 0, "best": float("-inf")}

    def objective(theta) -> OptimizerResult:
        result = resolve(make_policy(env, theta, {}), evaluator, initial, SEARCH_CAP)
        npv = max(item.npv for item in result.visited)
        calls["n"] += 1
        if npv > calls["best"]:
            calls["best"] = npv
            print(
                f"  оценка {calls['n']:3d}: новый максимум {npv / 1e9:.3f} млрд",
                flush=True,
            )
        return OptimizerResult(
            objective=npv,
            feasible=True,
            violations_by_scenario=(),
            provenance=provenance,
        )

    print(
        f"CMA-ES: параметров 10, бюджет {budget} оценок, потолок неподвижной "
        f"точки в поиске {SEARCH_CAP}, seed {SEED}",
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

    best_theta = report.best.theta
    print("\nпересчёт лучшей θ полным потолком:", flush=True)
    final = resolve(make_policy(env, best_theta, {}), evaluator, initial, FINAL_CAP)
    for item in final.visited:
        print(f"  {item.iteration}: ЧДД {item.npv / 1e9:8.3f} млрд", flush=True)
    best = max(final.visited, key=lambda item: item.npv)
    check = validate_static(best.schedule)
    delta = 100.0 * (best.npv - BASE_NPV) / BASE_NPV
    print(
        f"\nθ*: ЧДД {best.npv / 1e9:.3f} млрд ({delta:+.1f}% к базовому), "
        f"нарушений validate_static: {len(check.violations)}, "
        f"событий {check.n_control_events}, "
        f"сошлось: {final.converged}",
        flush=True,
    )
    print(f"canonical_schedule_hash: {hash_schedule(best.schedule)}", flush=True)

    return SearchOutcome(
        schedule=best.schedule,
        theta=best_theta,
        predicted_npv=best.npv,
        schedule_hash=hash_schedule(best.schedule),
        provenance=provenance,
        evaluations=report.evaluations,
    )


def main() -> int:
    outcome = run_search()
    out = Path("data/lambda-window-2007/cmaes.json")
    out.write_text(
        json.dumps(
            {
                "seed": SEED,
                "budget": BUDGET,
                "evaluations": outcome.evaluations,
                "search_cap": SEARCH_CAP,
                "final_cap": FINAL_CAP,
                "theta": dict(outcome.theta.values),
                "npv_predicted": outcome.predicted_npv,
                "npv_baseline": BASE_NPV,
                "canonical_schedule_hash": outcome.schedule_hash,
                "static_violations": len(validate_static(outcome.schedule).violations),
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
