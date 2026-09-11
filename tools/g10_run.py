from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.shared.resources import model_z_dir, normatives_xlsx
from backend.contexts.simulation.application.submission import submit_schedule
from backend.contexts.reservoir.infrastructure.opm_deck import OpmDeckEmitter
from backend.contexts.simulation.infrastructure.runner import deck_hashes, summary_spec_hash
from backend.contexts.constraints.domain.schema import default_config
from backend.contexts.constraints.domain.config import ArtifactHashes
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.policy.domain.policy import Theta
from backend.shared.hashing import hash_schedule
from backend.contexts.economics.infrastructure.normatives_io import load_normatives
from backend.contexts.economics.application.base_case import load_response_artifact
from backend.contexts.optimization.application.environment import (
    load_environment,
    make_evaluator,
    make_policy,
)
from backend.contexts.optimization.application.search_use_case import (
    DATASET,
    FINAL_CAP,
    LAMBDA,
    RESPONSE,
    SEED,
)
from backend.contexts.policy.domain.fixed_point import resolve
from backend.contexts.policy.domain.theta import default_theta
from backend.contexts.schedule.domain.canonical import canonical_part_hash

OUT = Path("data/g10-verification")
BASE_NPV = 11_873_676_459.64
INDEX = int(sys.argv[1])


def main() -> int:
    pool = json.loads((OUT / "pool.json").read_text(encoding="utf-8"))
    candidate = next(item for item in pool["candidates"] if item["index"] == INDEX)
    result_path = OUT / f"candidate-{INDEX:02d}.json"
    if result_path.exists():
        print(f"[{INDEX:02d}] already computed, skipped", flush=True)
        return 0

    model_dir = model_z_dir()
    normatives_path = normatives_xlsx()
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
    print(f"[{INDEX:02d}] plan rebuilt in {time.monotonic() - started:.0f} s", flush=True)
    if digest != candidate["canonical_schedule_hash"]:
        print(
            f"[{INDEX:02d}] HASH DIVERGED: {digest} against "
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
    print(f"[{INDEX:02d}] link A started", flush=True)
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
            f"[{INDEX:02d}] NPV not issued: status {submission.opm_run.status}, "
            f"identities failed {len(submission.failed_identities)}, in {elapsed / 60:.1f} min",
            flush=True,
        )
    else:
        print(
            f"[{INDEX:02d}] predicted {candidate['predicted_npv_final_cap'] / 1e9:.3f} - "
            f"actual {npv / 1e9:.3f} bln, violations {sum(counts.values())}, "
            f"in {elapsed / 60:.1f} min",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
