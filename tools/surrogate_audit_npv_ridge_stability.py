"""Audit the locked v3 ridge choice across repeated grouped CV splits.

This is a post-lock robustness audit, not another selection pass.  It compares
only the already fixed v2 (ridge 0.1) and v3 (ridge 0.3) specifications on the
historical train+validation population and never loads the retired test or the
blind OPM responses.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

if __package__:
    from tools.surrogate_benchmark_npv_models import (
        _cv_predict,
        _factories,
        _load_selection_data,
        _metrics,
        _view,
        _write_json,
    )
else:
    from surrogate_benchmark_npv_models import (
        _cv_predict,
        _factories,
        _load_selection_data,
        _metrics,
        _view,
        _write_json,
    )

BASELINE_ID = "krr-poly2-full-a0.1"
CANDIDATE_ID = "krr-poly2-full-a0.3"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260828)
    return parser


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
        "fraction_positive": statistics.fmean(value > 0.0 for value in values),
    }


def main() -> int:
    args = _parser().parse_args()
    if args.folds < 3 or args.repeats < 2:
        raise ValueError("audit requires at least 3 folds and 2 repeats")
    started = time.monotonic()
    matrix, target, groups, _, dataset_hash = _load_selection_data(
        args.tensors, args.labels, args.feature_cache
    )
    factories = _factories(seed=args.seed, trees=1)
    view = _view(matrix, BASELINE_ID)
    repeats = []
    for repeat in range(args.repeats):
        seed = args.seed + repeat
        predictions = {}
        metrics = {}
        for candidate_id in (BASELINE_ID, CANDIDATE_ID):
            predicted, _ = _cv_predict(
                factories[candidate_id],
                view,
                target,
                groups,
                folds=args.folds,
                seed=seed,
            )
            predictions[candidate_id] = predicted
            metrics[candidate_id] = _metrics(target, predicted)
        baseline = metrics[BASELINE_ID]
        candidate = metrics[CANDIDATE_ID]
        improvement = baseline["mae_rub"] - candidate["mae_rub"]
        rho_difference = (
            candidate["ranking"]["spearman_rank_correlation"]
            - baseline["ranking"]["spearman_rank_correlation"]
        )
        repeats.append(
            {
                "repeat": repeat + 1,
                "seed": seed,
                "baseline": baseline,
                "candidate": candidate,
                "mae_improvement_v2_minus_v3_rub": improvement,
                "spearman_difference_v3_minus_v2": rho_difference,
            }
        )
        print(
            f"repeat {repeat + 1}/{args.repeats}: "
            f"MAE improvement={improvement / 1e6:+.3f}m; "
            f"rho difference={rho_difference:+.4f}",
            flush=True,
        )
    mae = [item["mae_improvement_v2_minus_v3_rub"] for item in repeats]
    rho = [item["spearman_difference_v3_minus_v2"] for item in repeats]
    report = {
        "format": "aios.surrogate-locked-npv-stability-audit.v1",
        "purpose": "post-lock robustness audit; not model selection",
        "historical_test_read": False,
        "blind_response_read": False,
        "dataset_hash": dataset_hash,
        "selection_buckets": ["train", "validation"],
        "group_key": "canonical_schedule_hash",
        "n_rows": len(target),
        "n_groups": len(set(groups)),
        "folds": args.folds,
        "repeats": args.repeats,
        "seed_start": args.seed,
        "baseline_candidate_id": BASELINE_ID,
        "locked_candidate_id": CANDIDATE_ID,
        "summary": {
            "mae_improvement_v2_minus_v3_rub": _summary(mae),
            "spearman_difference_v3_minus_v2": _summary(rho),
        },
        "repeat_results": repeats,
        "seconds": time.monotonic() - started,
    }
    _write_json(args.output, report)
    print(f"audit written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
