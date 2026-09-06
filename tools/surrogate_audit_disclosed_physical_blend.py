"""Select a coarse physical/direct NPV blend by leave-one-blind-out transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

if __package__:
    from tools.surrogate_benchmark_npv_models import _metrics
    from tools.surrogate_evaluate_blind_npv import _bootstrap
else:
    from surrogate_benchmark_npv_models import _metrics
    from surrogate_evaluate_blind_npv import _bootstrap

from surrogate.npv_block_head import load_direct_npv_head

WEIGHTS = tuple(index / 10.0 for index in range(11))
PRECISION_AT_5_DIFFERENCE_MIN = -0.2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for split in ("blind1", "blind2"):
        parser.add_argument(f"--{split}-labels", type=Path, required=True)
        parser.add_argument(f"--{split}-physical", type=Path, required=True)
        parser.add_argument(f"--{split}-features", type=Path, required=True)
        parser.add_argument(f"--{split}-direct-head", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_split(
    name: str,
    *,
    labels_path: Path,
    physical_path: Path,
    features_path: Path,
    direct_head_path: Path,
) -> dict:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    physical = json.loads(physical_path.read_text(encoding="utf-8"))
    features = torch.load(features_path, map_location="cpu", weights_only=False)
    head = load_direct_npv_head(direct_head_path)
    if labels.get("historical_test_read") is not False:
        raise RuntimeError(f"{name}: labels may have read historical test")
    if (
        physical.get("format") != "aios.surrogate-blind-physical-npv.v1"
        or physical.get("response_data_read") is not False
        or physical.get("historical_test_read") is not False
    ):
        raise RuntimeError(f"{name}: physical prediction provenance is unsafe")
    if (
        features.get("response_data_read") is not False
        or features.get("historical_test_read") is not False
        or features.get("feature_set") != "economic"
    ):
        raise RuntimeError(f"{name}: feature provenance is unsafe")
    if labels.get("plan_hash") != physical.get("plan_hash"):
        raise RuntimeError(f"{name}: label/physical plan hashes differ")
    by_physical = {row["scenario_id"]: row for row in physical["rows"]}
    identities = features["identities"]
    keep = [
        index
        for index, identity in enumerate(identities)
        if identity["family"] != "BASELINE"
    ]
    scenario_ids = [identities[index]["scenario_id"] for index in keep]
    if len(scenario_ids) != 80 or len(set(scenario_ids)) != 80:
        raise RuntimeError(f"{name}: expected 80 unique non-baseline schedules")
    direct = head.predict_vectors(features["features"])[keep].numpy()
    actual = np.asarray([labels["rows"][item]["npv_rub"] for item in scenario_ids])
    physical_npv = np.asarray(
        [by_physical[item]["physical_npv_rub"] for item in scenario_ids]
    )
    baseline = np.asarray(
        [by_physical[item]["baseline_npv_rub"] for item in scenario_ids]
    )
    families = [by_physical[item]["family"] for item in scenario_ids]
    if not all(np.isfinite(item).all() for item in (actual, direct, physical_npv, baseline)):
        raise RuntimeError(f"{name}: predictions are not finite")
    return {
        "name": name,
        "actual": actual,
        "direct": direct,
        "physical": physical_npv,
        "baseline": baseline,
        "families": families,
        "head_version": head.version,
        "plan_hash": labels["plan_hash"],
        "input_sha256": {
            "labels": _sha256(labels_path),
            "physical": _sha256(physical_path),
            "features": _sha256(features_path),
            "direct_head": _sha256(direct_head_path),
        },
    }


def _candidate(split: dict, weight: float) -> tuple[np.ndarray, dict]:
    predicted = (1.0 - weight) * split["direct"] + weight * split["physical"]
    return predicted, _metrics(split["actual"], predicted)


def _at_5(metrics: dict) -> float:
    values = metrics["ranking"]["precision_at_k"]
    return float(values.get(5, values.get("5")))


def main() -> int:
    args = _parser().parse_args()
    splits = [
        _load_split(
            name,
            labels_path=getattr(args, f"{name}_labels"),
            physical_path=getattr(args, f"{name}_physical"),
            features_path=getattr(args, f"{name}_features"),
            direct_head_path=getattr(args, f"{name}_direct_head"),
        )
        for name in ("blind1", "blind2")
    ]
    baseline_metrics = {
        split["name"]: _metrics(split["actual"], split["baseline"])
        for split in splits
    }
    direct_metrics = {
        split["name"]: _metrics(split["actual"], split["direct"])
        for split in splits
    }
    physical_metrics = {
        split["name"]: _metrics(split["actual"], split["physical"])
        for split in splits
    }
    candidates = []
    for weight in WEIGHTS:
        metrics = {split["name"]: _candidate(split, weight)[1] for split in splits}
        feasible = all(
            item["rank_of_true_best"] <= 5
            and _at_5(item)
            >= _at_5(baseline_metrics[name]) + PRECISION_AT_5_DIFFERENCE_MIN
            for name, item in metrics.items()
        )
        candidates.append(
            {
                "physical_weight": weight,
                "direct_weight": 1.0 - weight,
                "feasible_optimizer_gate_both_splits": feasible,
                "mean_mae_rub": float(
                    np.mean([item["mae_rub"] for item in metrics.values()])
                ),
                "worst_true_best_rank": max(
                    item["rank_of_true_best"] for item in metrics.values()
                ),
                "metrics": metrics,
            }
        )
    feasible = [
        item for item in candidates if item["feasible_optimizer_gate_both_splits"]
    ]
    if not feasible:
        raise RuntimeError("no coarse blend satisfies optimizer gates on both splits")
    selected = min(
        feasible,
        key=lambda item: (
            item["mean_mae_rub"],
            item["physical_weight"],
        ),
    )
    weight = selected["physical_weight"]
    bootstrap = {}
    for split in splits:
        predicted, _ = _candidate(split, weight)
        rows = [
            {
                "family": family,
                "actual_npv_rub": float(actual),
                "v2_npv_rub": float(baseline),
                "v3_npv_rub": float(candidate),
            }
            for family, actual, baseline, candidate in zip(
                split["families"],
                split["actual"],
                split["baseline"],
                predicted,
                strict=True,
            )
        ]
        bootstrap[split["name"]] = _bootstrap(
            rows, replicates=args.bootstrap_replicates
        )
    report = {
        "format": "aios.surrogate-disclosed-physical-blend-audit.v1",
        "historical_test_read": False,
        "blind_responses_read_only_after_final_audits": True,
        "selection_design": "symmetric leave-one-blind-out direct transfer",
        "weight_grid": list(WEIGHTS),
        "selection_rule": {
            "require_true_best_rank_max_each_split": 5,
            "precision_at_5_difference_min_each_split": (
                PRECISION_AT_5_DIFFERENCE_MIN
            ),
            "then_minimize_mean_mae_rub": True,
            "then_minimize_physical_weight": True,
        },
        "splits": {
            split["name"]: {
                "n_scenarios": len(split["actual"]),
                "plan_hash": split["plan_hash"],
                "direct_head_version": split["head_version"],
                "input_sha256": split["input_sha256"],
                "baseline_metrics": baseline_metrics[split["name"]],
                "direct_metrics": direct_metrics[split["name"]],
                "physical_metrics": physical_metrics[split["name"]],
            }
            for split in splits
        },
        "candidates": candidates,
        "selected": selected,
        "selected_bootstrap_vs_baseline": bootstrap,
    }
    _write_json(args.output, report)
    print(
        f"selected physical weight={weight:g}; "
        f"mean MAE={selected['mean_mae_rub'] / 1e6:.3f}m",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
