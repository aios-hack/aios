"""G7: найденный CMA-ES план через настоящий OPM и звено А §10.5.

Запуск: `PYTHONPATH=. python -m optimizer.verification_run`. Нужны Docker с
образом OPM, чекпойнт суррогата, измеренная λ и `torch` (extras `ml`).

θ* воспроизводится тем же поиском с тем же seed — иначе плана взять неоткуда:
`Schedule*` не хранится, он функция от θ. Совпадение `canonical_schedule_hash`
с записанным в `cmaes.json` — проверка, что воспроизвели именно тот план.

Тракт вызывается `strict=False`: цепочку здесь разбирают, а не сдают.
Ожидается, что `validate_dynamic` остановит расписание на скважине 71 —
это известный блокер (открытый вопрос №17), и число заявлять нельзя. Ради
чего гоним: настоящий отклик OPM и посчитанный по нему ЧДД против 7.537
млрд, обещанных суррогатом.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from aios_backend.infrastructure.opm import submit_schedule
from aios_backend.infrastructure.opm.opm_deck import OpmDeckEmitter
from aios_backend.infrastructure.opm.runner import deck_hashes, summary_spec_hash
from aios_backend.domain.configuration.schema import default_config
from aios_backend.core.contracts import ArtifactHashes, Constraints, Schedule, Theta
from aios_backend.core.contracts.hashing import hash_schedule
from aios_backend.domain.schedule.canonical import canonical_part_hash
from aios_backend.domain.economics import load_normatives, load_response_artifact
from aios_backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from aios_backend.application.optimization.search import optimize
from aios_backend.application.optimization.search_run import BUDGET, FINAL_CAP, SEARCH_CAP, SEED
from aios_backend.domain.policy.fixed_point import resolve
from aios_backend.domain.policy.theta import default_theta
from aios_backend.core.contracts import OptimizerResult
from aios_backend.infrastructure.resources import chdd_python_dir, model_z_dir

DATASET = Path("../dataset-700/model-task34-700")
LAMBDA = Path("data/lambda-window-2007/lambda.json")
RESPONSE = Path("data/base_case/response.json")
WORK_ROOT = Path("data/g7-submission")
EXPECTED_HASH = None  # сверяется с cmaes.json; None — принять любой
BASE_NPV = 11_873_676_459.64


def verify_schedule(schedule: Schedule, work_root: Path):
    """Run the real OPM tract for the exact schedule supplied by a caller."""
    model_dir = model_z_dir()
    normatives_path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    normatives = load_normatives(normatives_path)
    emitter = OpmDeckEmitter(model_dir)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        hashes = deck_hashes(deck, schedule)
        summary_hash = summary_spec_hash(deck.summary_plan.spec)
    config = default_config(
        normatives,
        ArtifactHashes(
            deck_hash=hashes.deck_hash,
            history_prefix_hash=canonical_part_hash(schedule.initial_state),
            summary_spec_hash=summary_hash,
            groups_hash="0" * 64,
            dataset_version_hash="0" * 64,
            surrogate_checkpoint_hash="0" * 64,
        ),
        global_seed=SEED,
    )
    work_root.mkdir(parents=True, exist_ok=True)
    return submit_schedule(schedule, model_dir, work_root, config, constraints=Constraints(), strict=False)


def main() -> int:
    model_dir = model_z_dir()
    normatives_path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    env = load_environment(
        model_dir=model_dir,
        normatives_path=normatives_path,
        response_path=RESPONSE,
        checkpoint_path=DATASET / "model.pt",
        feature_context_path=DATASET / "feature_context.json",
        lambda_path=LAMBDA,
    )
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)

    def objective(theta) -> OptimizerResult:
        result = resolve(make_policy(env, theta, {}), evaluator, initial, SEARCH_CAP)
        return OptimizerResult(
            objective=max(item.npv for item in result.visited),
            feasible=True,
            violations_by_scenario=(),
            provenance={"seed": str(SEED)},
        )

    saved = json.loads(Path("data/lambda-window-2007/cmaes.json").read_text(encoding="utf-8"))
    # θ* берётся из отчёта поиска, а не воспроизводится поиском заново:
    # прогон CMA-ES стоит двадцать минут и ничего не добавляет, а хеш
    # восстановленного расписания всё равно сверяется с записанным.
    theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)
    started = time.monotonic()
    final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
    best = max(final.visited, key=lambda item: item.npv)
    schedule = best.schedule
    actual_hash = hash_schedule(schedule)
    print(
        f"план восстановлен из θ* за {time.monotonic() - started:.1f} с, "
        f"предсказание суррогата {best.npv / 1e9:.3f} млрд",
        flush=True,
    )
    print(f"canonical_schedule_hash: {actual_hash}", flush=True)
    expected = EXPECTED_HASH or saved["canonical_schedule_hash"]
    if actual_hash != expected:
        print(f"ХЕШ РАЗОШЁЛСЯ с записанным {expected}", flush=True)
        return 3
    print("хеш совпал с записанным в cmaes.json", flush=True)

    print("\nзвено А: эмит, прогон Flow, отклик, гейт, экономика...", flush=True)
    started = time.monotonic()
    result = verify_schedule(schedule, WORK_ROOT)
    print(f"тракт отработал за {(time.monotonic() - started) / 60:.1f} мин", flush=True)

    print(f"\nстатус прогона: {result.opm_run.status}", flush=True)
    print(f"годен к сдаче (sound): {result.sound}", flush=True)
    for check in result.identities:
        mark = "OK " if check.holds else "НЕТ"
        print(f"  [{mark}] {check.name}", flush=True)
        if not check.holds:
            print(f"        {check.detail}", flush=True)
    if result.dynamic_report is not None:
        counts = {}
        for violation in result.dynamic_report.violations:
            counts[violation.kind] = counts.get(violation.kind, 0) + 1
        print(f"\nvalidate_dynamic: {len(result.dynamic_report.violations)} нарушений", flush=True)
        for kind, count in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"  {kind}: {count}", flush=True)
    if result.final_npv is not None:
        npv = result.final_npv.npv_methodology
        print(
            f"\nЧДД по настоящему прогону: {npv / 1e9:.3f} млрд "
            f"({100.0 * (npv - BASE_NPV) / BASE_NPV:+.1f}% к базовому), "
            f"предсказание суррогата было {best.npv / 1e9:.3f} млрд "
            f"(ошибка {100.0 * (best.npv - npv) / npv:+.1f}%)",
            flush=True,
        )
    Path("data/g7-result.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": actual_hash,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "failed_identities": [c.name for c in result.failed_identities],
                "npv_surrogate": best.npv,
                "npv_opm": result.final_npv.npv_methodology if result.final_npv else None,
                "npv_baseline": BASE_NPV,
                "dynamic_violations": len(result.dynamic_report.violations)
                if result.dynamic_report
                else None,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print("\nитог записан: data/g7-result.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
