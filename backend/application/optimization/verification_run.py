"""G7: найденный CMA-ES план через настоящий OPM и звено А §10.5.

Запуск: `PYTHONPATH=. python -m backend.application.optimization.verification_run`. Нужны Docker с
образом OPM, чекпойнт суррогата, измеренная λ и `torch` (extras `ml`).

θ* читается из `cmaes.json`, затем `Schedule*` воспроизводится production-
ансамблем и политикой. Совпадение `canonical_schedule_hash` доказывает, что
в OPM уходит ровно отобранный самосогласованный план.

Тракт вызывается `strict=False`, чтобы сохранить полный диагностический
отчёт даже при нарушении. Ограничения воды и кейса передаются те же, что в
поиске; сдаваемым числом результат становится только при `result.sound`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.infrastructure.opm import submit_schedule
from backend.infrastructure.opm.opm_deck import OpmDeckEmitter
from backend.infrastructure.opm.runner import deck_hashes, summary_spec_hash
from backend.domain.configuration.schema import default_config
from backend.core.contracts import ArtifactHashes, Schedule, Theta
from backend.core.contracts.hashing import canonical_bytes, hash_schedule
from backend.domain.schedule.canonical import canonical_part_hash
from backend.domain.economics import (
    load_normatives,
    load_response_artifact,
    save_response_artifact,
)
from backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from backend.application.optimization.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.application.optimization.search_run import (
    FINAL_CAP,
    SEED,
    _repair_predicted_water_balance,
)
from backend.domain.policy.fixed_point import resolve
from backend.domain.policy.theta import default_theta
from backend.infrastructure.resources import chdd_python_dir, model_z_dir
from backend.application.cases import constraints_from_json

LAMBDA = Path("data/lambda-window-2007/lambda.json")
RESPONSE = Path("data/base_case/response.json")
CONSTRAINTS = Path("config/competition-constraints.json")
WORK_ROOT = Path("data/g7-submission")
EXPECTED_HASH = None  # сверяется с cmaes.json; None — принять любой
BASE_NPV = 11_873_676_459.64
OIL_DENSITY_T_PER_M3 = 0.9131


def _load_constraints():
    return constraints_from_json(
        json.loads(CONSTRAINTS.read_text(encoding="utf-8"))
    )


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
    return submit_schedule(
        schedule,
        model_dir,
        work_root,
        config,
        constraints=_load_constraints(),
        strict=False,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )


def persist_observation(
    schedule: Schedule,
    result,
    *,
    predicted_npv: float | None,
    observation_root: Path = Path("data/opm-observations"),
    metadata: dict[str, object] | None = None,
) -> Path:
    """Persist an OPM truth point for diagnostics and later active learning."""

    schedule_hash = hash_schedule(schedule)
    observation_dir = observation_root / schedule_hash
    observation_dir.mkdir(parents=True, exist_ok=True)
    (observation_dir / "schedule.json").write_bytes(canonical_bytes(schedule))
    if result.response is not None:
        save_response_artifact(result.response, observation_dir / "response.json")
    if result.dynamic_report is not None:
        (observation_dir / "dynamic-report.json").write_bytes(
            canonical_bytes(result.dynamic_report)
        )
    final_summary = None
    if result.final_npv is not None:
        final_summary = {
            "npv_methodology": result.final_npv.npv_methodology,
            "source_run_id": result.final_npv.source_run_id,
            "source_response_hash": result.final_npv.source_response_hash,
            "economics_config_hash": result.final_npv.economics_config_hash,
            "methodology_version_hash": result.final_npv.methodology_version_hash,
        }
        (observation_dir / "final-npv-summary.json").write_text(
            json.dumps(final_summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    (observation_dir / "observation.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": schedule_hash,
                "run_id": result.opm_run.run_id,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "predicted_npv": predicted_npv,
                "opm_npv": final_summary["npv_methodology"] if final_summary else None,
                "dynamic_violations": (
                    len(result.dynamic_report.violations)
                    if result.dynamic_report is not None
                    else None
                ),
                "metadata": metadata or {},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return observation_dir


def main() -> int:
    model_dir = model_z_dir()
    normatives_path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    runtime = resolve_runtime_artifacts()
    constraints = _load_constraints()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=normatives_path,
        response_path=RESPONSE,
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        lambda_path=LAMBDA,
        constraints=constraints,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )
    validate_runtime_economic_head(runtime, env.npv_head)
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)

    saved = json.loads(Path("data/lambda-window-2007/cmaes.json").read_text(encoding="utf-8"))
    # θ* берётся из отчёта поиска, а не воспроизводится поиском заново:
    # прогон CMA-ES стоит двадцать минут и ничего не добавляет, а хеш
    # восстановленного расписания всё равно сверяется с записанным.
    theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)
    started = time.monotonic()
    final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
    schedule, repaired_prediction, _dynamic, repair_rounds = _repair_predicted_water_balance(
        env, evaluator, final.schedule
    )
    actual_hash = hash_schedule(schedule)
    print(
        f"план восстановлен из θ* за {time.monotonic() - started:.1f} с, "
        f"предсказание economic head {final.npv / 1e9:.3f} млрд, "
        f"policy-stable={final.self_consistent}, water-repair={repair_rounds}",
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
        surrogate_npv = repaired_prediction.npv
        print(
            f"\nЧДД по настоящему прогону: {npv / 1e9:.3f} млрд "
            f"({100.0 * (npv - BASE_NPV) / BASE_NPV:+.1f}% к базовому), "
            f"предсказание economic head было {surrogate_npv / 1e9:.3f} млрд "
            f"(ошибка {100.0 * (surrogate_npv - npv) / npv:+.1f}%)",
            flush=True,
        )
    persist_observation(
        schedule,
        result,
        predicted_npv=repaired_prediction.npv,
        metadata={"candidate": "cmaes-policy", "water_repair_rounds": repair_rounds},
    )
    Path("data/g7-result.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": actual_hash,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "failed_identities": [c.name for c in result.failed_identities],
                "npv_surrogate": repaired_prediction.npv,
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
