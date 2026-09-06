"""G7: найденный CMA-ES план через настоящий OPM и звено А §10.5.

Запуск: `PYTHONPATH=. python -m bridge.submission_run`. Нужны Docker с
образом OPM, чекпойнт суррогата, измеренная λ и `torch` (extras `ml`).

θ* воспроизводится тем же поиском с тем же seed — иначе плана взять неоткуда:
`Schedule*` не хранится, он функция от θ. Совпадение `canonical_schedule_hash`
с записанным в `cmaes.json` — проверка, что воспроизвели именно тот план.

Тракт вызывается `strict=False`: цепочку здесь разбирают, а не сдают.
Production-профиль Constraints обязателен и сверяется по хешу с тем, на
котором найден θ. Фактический баланс добытой и закачанной воды проверяется
здесь впервые на настоящем отклике OPM; суррогатный поиск гарантирует только
командный бюджет, потому что старый trajectory surrogate не обучался на
режимах резко ограниченной воды.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import conftest
from bridge import submit_schedule
from bridge.opm_deck import OpmDeckEmitter
from bridge.runner import deck_hashes, summary_spec_hash
from config.schema import default_config
from contracts import ArtifactHashes, Theta, content_hash
from contracts.hashing import canonical_bytes, hash_schedule
from schedule.canonical import canonical_part_hash
from economics import (
    OPM_CONTROL_HORIZON_BASE_NPV_RUB,
    load_normatives,
    load_response_artifact,
    save_response_artifact,
)
from optimizer.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from optimizer.schedule_search import load_environment, make_evaluator, make_policy
from optimizer.search_run import (
    CONSTRAINTS_PATH,
    FINAL_CAP,
    LAMBDA,
    MODEL_DIR,
    NORMATIVES,
    RESPONSE,
    SEARCH_OUTPUT,
    SEED,
)
from policy.fixed_point import resolve
from policy.theta import default_theta
from ui.scenarios import constraints_to_json, load_constraints_file

WORK_ROOT = Path(os.environ.get("AIOS_SUBMISSION_WORK_ROOT", "data/g7-submission"))
RESULT_PATH = Path(os.environ.get("AIOS_RESULT_PATH", "data/g7-result.json"))
SUBMISSION_SCHEDULE_PATH = Path(
    os.environ.get("AIOS_SUBMISSION_SCHEDULE_PATH", "data/wells_schedule.inc")
)
EXPECTED_HASH = None  # сверяется с cmaes.json; None — принять любой
UNCONSTRAINED_BASE_NPV = OPM_CONTROL_HORIZON_BASE_NPV_RUB


def main() -> int:
    constraints = load_constraints_file(
        CONSTRAINTS_PATH, require_water_supply=True
    )
    model_dir = MODEL_DIR
    normatives_path = NORMATIVES
    if not model_dir.is_dir():
        discovered = conftest.model_z_dir()
        if discovered is None:
            raise FileNotFoundError(f"каталог Model_Z не найден: {model_dir}")
        model_dir = discovered
    if not normatives_path.is_file():
        chdd = conftest.chdd_python_dir()
        if chdd is None:
            raise FileNotFoundError(f"нормативы ЧДД не найдены: {normatives_path}")
        normatives_path = chdd / "input" / "Нормативы_ЧДД.xlsx"
    artifacts = resolve_runtime_artifacts()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=normatives_path,
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        lambda_path=LAMBDA,
        constraints=constraints,
    )
    validate_runtime_economic_head(artifacts, env.npv_head)
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)

    saved = json.loads(SEARCH_OUTPUT.read_text(encoding="utf-8"))
    constraints_hash = hashlib.sha256(
        canonical_bytes(constraints_to_json(constraints))
    ).hexdigest()
    if saved.get("constraints_hash") != constraints_hash:
        raise ValueError(
            "cmaes.json получен с другим или неуказанным профилем Constraints; "
            "старый unconstrained θ нельзя отправлять в production-прогон"
        )
    # θ* берётся из отчёта поиска, а не воспроизводится поиском заново:
    # прогон CMA-ES стоит двадцать минут и ничего не добавляет, а хеш
    # восстановленного расписания всё равно сверяется с записанным.
    theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)
    started = time.monotonic()
    final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
    schedule = final.schedule
    actual_hash = hash_schedule(schedule)
    print(
        f"план восстановлен из θ* за {time.monotonic() - started:.1f} с, "
        f"предсказание суррогата {final.npv / 1e9:.3f} млрд",
        flush=True,
    )
    print(f"canonical_schedule_hash: {actual_hash}", flush=True)
    expected = EXPECTED_HASH or saved["canonical_schedule_hash"]
    if actual_hash != expected:
        print(f"ХЕШ РАЗОШЁЛСЯ с записанным {expected}", flush=True)
        return 3
    print("хеш совпал с записанным в cmaes.json", flush=True)

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
            groups_hash=env.groups.group_hash,
            dataset_version_hash=env.model.dataset_hash,
            surrogate_checkpoint_hash=env.model.version,
        ),
        global_seed=SEED,
    )

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    print("\nзвено А: эмит, прогон Flow, отклик, гейт, экономика...", flush=True)
    started = time.monotonic()
    result = submit_schedule(
        schedule,
        model_dir,
        WORK_ROOT,
        config,
        constraints=constraints,
        require_water_supply=True,
        groups=env.groups,
        strict=False,
    )
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
            f"\nЧДД по настоящему прогону: {npv / 1e9:.3f} млрд; "
            f"предсказание суррогата было {final.npv / 1e9:.3f} млрд "
            f"(ошибка {100.0 * (final.npv - npv) / npv:+.1f}%). "
            "Старый unconstrained baseline не используется для сравнения.",
            flush=True,
        )
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    emitted_schedule = WORK_ROOT / "deck" / "Model_Z_sch.inc"
    if emitted_schedule.is_file():
        SUBMISSION_SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(emitted_schedule, SUBMISSION_SCHEDULE_PATH)
    response_path = RESULT_PATH.with_name("response.json")
    if result.response is not None:
        save_response_artifact(result.response, response_path)
    RESULT_PATH.write_text(
        json.dumps(
            {
                "format": "aios.e2e-result.v1",
                "canonical_schedule_hash": actual_hash,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "failed_identities": [c.name for c in result.failed_identities],
                "npv_surrogate": final.npv,
                "npv_opm": result.final_npv.npv_methodology if result.final_npv else None,
                "npv_baseline_unconstrained": UNCONSTRAINED_BASE_NPV,
                "surrogate": {
                    "runtime_source": artifacts.source,
                    "trajectory_version": env.model.version,
                    "dataset_hash": env.model.dataset_hash,
                    "npv_head_version": (
                        env.npv_head.version if env.npv_head is not None else None
                    ),
                },
                "constraints_hash": constraints_hash,
                "search_artifact": str(SEARCH_OUTPUT),
                "submission_schedule": (
                    str(SUBMISSION_SCHEDULE_PATH)
                    if SUBMISSION_SCHEDULE_PATH.is_file()
                    else None
                ),
                "response_artifact": (
                    str(response_path) if response_path.is_file() else None
                ),
                "dynamic_violations": len(result.dynamic_report.violations)
                if result.dynamic_report
                else None,
                "blocking_dynamic_violations": len(
                    result.dynamic_report.blocking_violations
                )
                if result.dynamic_report
                else None,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\nитог записан: {RESULT_PATH}", flush=True)
    if SUBMISSION_SCHEDULE_PATH.is_file():
        print(f"расписание для сдачи: {SUBMISSION_SCHEDULE_PATH}", flush=True)
        print(
            f"content_hash: {content_hash(SUBMISSION_SCHEDULE_PATH.read_bytes())}",
            flush=True,
        )
    return 0 if result.sound else 6


if __name__ == "__main__":
    sys.exit(main())
