"""Прогон текущей политики через настоящий OPM с разложением по закачке.

Нужен, чтобы мерить вклад каждой правки R1 по отдельности: θ берётся та же,
что дала план G7 (`cmaes.json`), меняется только код правила, и разница
целиком относится к правке.

Запуск: `PYTHONPATH=. python tools/r1_check.py <метка>`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import conftest

# `optimizer.search_run` читает sys.argv на импорте (там это точка входа
# поиска), а сюда приходит текстовая метка прогона. Подменяем argv на время
# импорта, иначе модуль падает на int() ещё до первой строки нашей логики.
_ARGV = sys.argv[:]
sys.argv = sys.argv[:1]

from backend.infrastructure.opm import submit_schedule
from backend.infrastructure.opm.opm_deck import OpmDeckEmitter
from backend.infrastructure.opm.runner import deck_hashes, summary_spec_hash
from backend.domain.configuration.schema import default_config
from backend.core.contracts import ArtifactHashes, Constraints, EventKind, Theta
from backend.core.contracts.hashing import hash_schedule
from backend.domain.economics import load_normatives, load_response_artifact
from backend.domain.economics.base_case import analyze_base_case
from backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from backend.application.optimization.search_run import DATASET, FINAL_CAP, LAMBDA, RESPONSE, SEED
from backend.domain.policy.fixed_point import resolve
from backend.domain.policy.theta import default_theta
from backend.domain.schedule.canonical import canonical_part_hash

sys.argv = _ARGV
LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"
OUT = Path("data/r1-checks")
BASE_NPV = 11_873_676_459.64


def injection_by_step(schedule) -> dict[int, float]:
    total: dict[int, float] = {}
    for event in schedule.control_events:
        if event.kind is EventKind.SET_RATE and event.value:
            total[event.control_step] = total.get(event.control_step, 0.0) + event.value
    return total


def main() -> int:
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
    saved = json.loads(Path("data/lambda-window-2007/cmaes.json").read_text(encoding="utf-8"))
    theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)

    started = time.monotonic()
    final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
    best = max(final.visited, key=lambda item: item.npv)
    schedule = best.schedule
    digest = hash_schedule(schedule)
    print(f"[{LABEL}] план восстановлен за {time.monotonic() - started:.0f} с, {digest[:12]}…")
    print(f"[{LABEL}] предсказание суррогата {best.npv / 1e9:.3f} млрд")

    ours = injection_by_step(schedule)
    base = injection_by_step(env.base_schedule)
    steps = sorted(set(ours) | set(base))
    o = sorted(ours.get(s, 0.0) for s in steps)
    b = sorted(base.get(s, 0.0) for s in steps)
    print(
        f"[{LABEL}] закачка, медиана на шаг: наша {o[len(o) // 2]:,.0f} против "
        f"базовой {b[len(b) // 2]:,.0f} м³/сут "
        f"({100.0 * o[len(o) // 2] / max(1e-9, b[len(b) // 2]):.1f}%)"
    )

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
    work_root = OUT / LABEL
    work_root.mkdir(parents=True, exist_ok=True)
    print(f"[{LABEL}] звено А пошло", flush=True)
    started = time.monotonic()
    submission = submit_schedule(
        schedule, model_dir, work_root, config, constraints=Constraints(), strict=False
    )
    elapsed = time.monotonic() - started

    counts: dict[str, int] = {}
    if submission.dynamic_report is not None:
        for violation in submission.dynamic_report.violations:
            kind = getattr(violation.kind, "name", None) or str(violation.kind)
            counts[kind] = counts.get(kind, 0) + 1
    npv = submission.final_npv.npv_methodology if submission.final_npv else None
    print(f"[{LABEL}] статус {submission.opm_run.status}, за {elapsed / 60:.1f} мин")
    if npv is not None:
        print(
            f"[{LABEL}] ЧДД по OPM {npv / 1e9:.3f} млрд "
            f"({100.0 * (npv - BASE_NPV) / BASE_NPV:+.1f}% к базовому)"
        )
        analysis = analyze_base_case(
            submission.response, env.deck_dates, env.t0_deck_date_index, normatives, env.policies
        )
        v = analysis.volumes
        print(
            f"[{LABEL}] натура: нефть {v.oil_mass_t / 1e3:,.1f} тыс. т, "
            f"жидкость {v.liquid_volume_m3 / 1e3:,.1f}, "
            f"закачка {v.injection_volume_m3 / 1e3:,.1f} тыс. м³"
        )
    print(f"[{LABEL}] нарушений {sum(counts.values())}: {counts}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{LABEL}.json").write_text(
        json.dumps(
            {
                "label": LABEL,
                "canonical_schedule_hash": digest,
                "npv_surrogate": best.npv,
                "npv_opm": npv,
                "npv_baseline": BASE_NPV,
                "run_status": str(submission.opm_run.status),
                "sound": submission.sound,
                "dynamic_violations_by_kind": counts,
                "injection_median_ours": o[len(o) // 2],
                "injection_median_base": b[len(b) // 2],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
