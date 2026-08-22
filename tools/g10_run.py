"""G10, фаза 2: один кандидат из пула через настоящий OPM.

Отдельный процесс на кандидата: прогон Flow стоит около 513 с и держится
на своём контейнере, поэтому параллелить дешевле процессами, чем потоками —
экономика отклика считается на Python и упирается в GIL.

План не передаётся между процессами и не сериализуется: он функция от θ,
и восстановить его неподвижной точкой стоит 16 с против 240 МБ обмена.

Запуск: `PYTHONPATH=. python tools/g10_run.py <индекс кандидата>`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import conftest
from backend.infrastructure.opm import submit_schedule
from backend.infrastructure.opm.opm_deck import OpmDeckEmitter
from backend.infrastructure.opm.runner import deck_hashes, summary_spec_hash
from backend.domain.configuration.schema import default_config
from backend.core.contracts import ArtifactHashes, Constraints, Theta
from backend.core.contracts.hashing import hash_schedule
from backend.domain.economics import load_normatives, load_response_artifact
from backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from backend.application.optimization.search_run import DATASET, FINAL_CAP, LAMBDA, RESPONSE, SEED
from backend.domain.policy.fixed_point import resolve
from backend.domain.policy.theta import default_theta
from backend.domain.schedule.canonical import canonical_part_hash

OUT = Path("data/g10-verification")
BASE_NPV = 11_873_676_459.64
INDEX = int(sys.argv[1])


def main() -> int:
    pool = json.loads((OUT / "pool.json").read_text(encoding="utf-8"))
    candidate = next(item for item in pool["candidates"] if item["index"] == INDEX)
    result_path = OUT / f"candidate-{INDEX:02d}.json"
    if result_path.exists():
        print(f"[{INDEX:02d}] уже посчитан, пропуск", flush=True)
        return 0

    model_dir = conftest.model_z_dir()
    normatives_path = conftest.chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
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
    theta = Theta(values=dict(candidate["theta"]), bounds=default_theta().bounds)

    started = time.monotonic()
    final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
    best = max(final.visited, key=lambda item: item.npv)
    schedule = best.schedule
    digest = hash_schedule(schedule)
    print(f"[{INDEX:02d}] план восстановлен за {time.monotonic() - started:.0f} с", flush=True)
    if digest != candidate["canonical_schedule_hash"]:
        # Расхождение означает, что план перестал быть функцией от θ:
        # дальше считать нечего, число будет не про того кандидата.
        print(
            f"[{INDEX:02d}] ХЕШ РАЗОШЁЛСЯ: {digest} против "
            f"{candidate['canonical_schedule_hash']}",
            flush=True,
        )
        return 3

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

    work_root = OUT / f"work-{INDEX:02d}"
    work_root.mkdir(parents=True, exist_ok=True)
    print(f"[{INDEX:02d}] звено А пошло", flush=True)
    started = time.monotonic()
    submission = submit_schedule(
        schedule, model_dir, work_root, config, constraints=Constraints(), strict=False
    )
    elapsed = time.monotonic() - started

    counts: dict[str, int] = {}
    if submission.dynamic_report is not None:
        for violation in submission.dynamic_report.violations:
            # ViolationKind — enum без порядка, а отчёт пишется с sort_keys:
            # ключом идёт имя, иначе json не соберётся.
            kind = getattr(violation.kind, "name", None) or str(violation.kind)
            counts[kind] = counts.get(kind, 0) + 1
    npv = submission.final_npv.npv_methodology if submission.final_npv else None
    payload = {
        "index": INDEX,
        "theta": candidate["theta"],
        "canonical_schedule_hash": digest,
        "predicted_npv": candidate["predicted_npv_final_cap"],
        "predicted_npv_search_cap": candidate["predicted_npv_search_cap"],
        "actual_npv": npv,
        "npv_baseline": BASE_NPV,
        "run_status": str(submission.opm_run.status),
        "run_id": submission.opm_run.run_id,
        "sound": submission.sound,
        "failed_identities": [check.name for check in submission.failed_identities],
        "dynamic_violations": sum(counts.values()) if submission.dynamic_report else None,
        "dynamic_violations_by_kind": counts,
        "elapsed_seconds": elapsed,
    }
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    if npv is None:
        print(
            f"[{INDEX:02d}] ЧДД не выдан: статус {submission.opm_run.status}, "
            f"тождеств не сошлось {len(submission.failed_identities)}, за {elapsed / 60:.1f} мин",
            flush=True,
        )
    else:
        print(
            f"[{INDEX:02d}] предсказано {candidate['predicted_npv_final_cap'] / 1e9:.3f} — "
            f"факт {npv / 1e9:.3f} млрд, нарушений {sum(counts.values())}, "
            f"за {elapsed / 60:.1f} мин",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
