"""Детализация нарушений динамики у выбранных кандидатов G10.

Прогон берётся из кеша `data/g10-verification/work-XX`, симулятор не
запускается. Нужно ровно одно: увидеть, на каких скважинах и шагах сидят
нарушения, потому что от этого зависит, чья это проблема — дека или наша.

Запуск: `PYTHONPATH=. python tools/g10_violations.py <индекс> [<индекс> …]`.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import conftest
from bridge import submit_schedule
from bridge.opm_deck import OpmDeckEmitter
from bridge.runner import deck_hashes, summary_spec_hash
from config.schema import default_config
from contracts import ArtifactHashes, Constraints, Theta
from economics import load_normatives, load_response_artifact
from optimizer.schedule_search import load_environment, make_evaluator, make_policy
from optimizer.search_run import DATASET, FINAL_CAP, LAMBDA, RESPONSE, SEED
from policy.fixed_point import resolve
from policy.theta import default_theta
from schedule.canonical import canonical_part_hash

OUT = Path("data/g10-verification")


def main() -> int:
    pool = json.loads((OUT / "pool.json").read_text(encoding="utf-8"))
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
    normatives = load_normatives(normatives_path)
    emitter = OpmDeckEmitter(model_dir)

    for raw in sys.argv[1:]:
        index = int(raw)
        candidate = next(item for item in pool["candidates"] if item["index"] == index)
        theta = Theta(values=dict(candidate["theta"]), bounds=default_theta().bounds)
        final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
        schedule = max(final.visited, key=lambda item: item.npv).schedule
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
        submission = submit_schedule(
            schedule,
            model_dir,
            OUT / f"work-{index:02d}",
            config,
            constraints=Constraints(),
            strict=False,
        )
        report = submission.dynamic_report
        print(f"\n=== кандидат {index}: нарушений {len(report.violations) if report else 0} ===")
        if report is None:
            continue
        by_kind_well: dict[str, Counter] = {}
        for violation in report.violations:
            kind = getattr(violation.kind, "name", None) or str(violation.kind)
            by_kind_well.setdefault(kind, Counter())[violation.well] += 1
        for kind, wells in sorted(by_kind_well.items(), key=lambda item: -sum(item[1].values())):
            total = sum(wells.values())
            listed = ", ".join(f"скв {well}×{n}" for well, n in wells.most_common(8))
            print(f"  {kind:<32} {total:3d}: {listed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
