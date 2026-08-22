"""G10, фаза 1: пул кандидатов CMA-ES и top-K по предсказанию суррогата.

Пункт 4 запросов Андрея (`SURROGATE-REQUESTS-20.08.md`). Поиск тот же, что в
`optimizer/search_run.py`, с тем же seed — первое место обязано совпасть с
записанной θ*. Отличие одно: сохраняется вся история оценок, а не только
лучшая, потому что проверять настоящим OPM предстоит top-K, а не победителя.

Запуск: `PYTHONPATH=. python tools/g10_pool.py [K] [бюджет]`.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import conftest
from backend.core.contracts import OptimizerResult
from backend.core.contracts.hashing import hash_schedule
from backend.domain.economics import load_response_artifact
from backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from backend.application.optimization.search import optimize
from backend.application.optimization.search_run import BUDGET, DATASET, FINAL_CAP, LAMBDA, RESPONSE, SEARCH_CAP, SEED
from backend.domain.policy.fixed_point import resolve
from backend.domain.policy.theta import default_theta

OUT = Path("data/g10-verification")
TOP_K = int(sys.argv[1]) if len(sys.argv) > 1 else 40
POOL_BUDGET = int(sys.argv[2]) if len(sys.argv) > 2 else BUDGET


def main() -> int:
    env = load_environment(
        model_dir=conftest.model_z_dir(),
        normatives_path=conftest.chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=DATASET / "model.pt",
        feature_context_path=DATASET / "feature_context.json",
        lambda_path=LAMBDA,
    )
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)
    calls = {"n": 0}

    def objective(theta) -> OptimizerResult:
        result = resolve(make_policy(env, theta, {}), evaluator, initial, SEARCH_CAP)
        calls["n"] += 1
        if calls["n"] % 10 == 0:
            print(f"  оценка {calls['n']:3d}/{POOL_BUDGET}", flush=True)
        return OptimizerResult(
            objective=max(item.npv for item in result.visited),
            feasible=True,
            violations_by_scenario=(),
            provenance={"seed": str(SEED)},
        )

    print(f"CMA-ES: бюджет {POOL_BUDGET}, seed {SEED}, потолок поиска {SEARCH_CAP}", flush=True)
    started = time.monotonic()
    report = optimize(objective, default_theta(), seed=SEED, max_evaluations=POOL_BUDGET)
    print(
        f"поиск закончен за {(time.monotonic() - started) / 60:.1f} мин, "
        f"оценок {report.evaluations}, поколений {report.generations}",
        flush=True,
    )

    ordered = sorted(report.history, key=lambda item: -item.result.objective)
    # Разные θ могут давать одно расписание: платить за одинаковый прогон OPM
    # дважды незачем, дедупликация идёт по хешу плана, а не по θ.
    chosen: list[dict] = []
    seen: set[str] = set()
    print(f"\nвосстанавливаем планы top-{TOP_K} полным потолком {FINAL_CAP}:", flush=True)
    for item in ordered:
        if len(chosen) >= TOP_K:
            break
        started = time.monotonic()
        final = resolve(make_policy(env, item.theta, {}), evaluator, initial, FINAL_CAP)
        best = max(final.visited, key=lambda visited: visited.npv)
        digest = hash_schedule(best.schedule)
        if digest in seen:
            print(f"  пропуск: план повторяет уже отобранный ({digest[:12]}…)", flush=True)
            continue
        seen.add(digest)
        chosen.append(
            {
                "index": len(chosen),
                "theta": dict(item.theta.values),
                "predicted_npv_search_cap": item.result.objective,
                "predicted_npv_final_cap": best.npv,
                "canonical_schedule_hash": digest,
                "fixed_point_converged": final.converged,
            }
        )
        print(
            f"  {len(chosen):2d}/{TOP_K}: предсказание {best.npv / 1e9:7.3f} млрд "
            f"(поисковое {item.result.objective / 1e9:7.3f}), {digest[:12]}…, "
            f"{time.monotonic() - started:.0f} с",
            flush=True,
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pool.json").write_text(
        json.dumps(
            {
                "seed": SEED,
                "pool_budget": POOL_BUDGET,
                "evaluations": report.evaluations,
                "search_cap": SEARCH_CAP,
                "final_cap": FINAL_CAP,
                "top_k_requested": TOP_K,
                "candidates": chosen,
                "model_version": env.model.version,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\nпул записан: {OUT / 'pool.json'}, кандидатов {len(chosen)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
