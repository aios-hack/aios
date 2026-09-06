"""Select a v6 physical blend by three-way leave-one-blind-out transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from surrogate.npv_block_head import load_direct_npv_head
from tools.surrogate_benchmark_npv_models import _metrics
from tools.surrogate_evaluate_blind_npv import _bootstrap

SPLITS = ("blind1", "blind2", "blind3")
WEIGHTS = tuple(index / 20.0 for index in range(21))
REFERENCE_PHYSICAL_WEIGHT = 0.2
PRECISION_AT_5_DIFFERENCE_MIN = -0.2
SPEARMAN_DIFFERENCE_MIN = -0.03
MAX_MAE_REGRESSION_RUB = 5_000_000.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for split in SPLITS:
        parser.add_argument(f"--{split}-labels", type=Path, required=True)
        parser.add_argument(f"--{split}-physical", type=Path, required=True)
        parser.add_argument(f"--{split}-features", type=Path, required=True)
        parser.add_argument(f"--{split}-candidate-head", type=Path, required=True)
        parser.add_argument(f"--{split}-reference-head", type=Path, required=True)
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
    if path.exists():
        raise FileExistsError(f"refusing to overwrite disclosed v6 audit: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _at_5(metrics: dict) -> float:
    values = metrics["ranking"]["precision_at_k"]
    return float(values.get(5, values.get("5")))


def _load_split(
    name: str,
    *,
    labels_path: Path,
    physical_path: Path,
    features_path: Path,
    candidate_head_path: Path,
    reference_head_path: Path,
) -> dict:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    physical = json.loads(physical_path.read_text(encoding="utf-8"))
    features = torch.load(features_path, map_location="cpu", weights_only=False)
    candidate_head = load_direct_npv_head(candidate_head_path)
    reference_head = load_direct_npv_head(reference_head_path)
    if (
        labels.get("format") != "aios.surrogate-disclosed-blind-npv-labels.v1"
        or labels.get("historical_test_read") is not False
        or labels.get("blind_response_read_after_final_audit") is not True
    ):
        raise RuntimeError(f"{name}: label disclosure provenance is unsafe")
    if (
        physical.get("format") != "aios.surrogate-blind-physical-npv.v1"
        or physical.get("response_data_read") is not False
        or physical.get("historical_test_read") is not False
    ):
        raise RuntimeError(f"{name}: physical provenance is unsafe")
    if (
        features.get("format") != "aios.surrogate-blind-npv-features.v2"
        or features.get("response_data_read") is not False
        or features.get("historical_test_read") is not False
        or features.get("feature_set") != "economic"
    ):
        raise RuntimeError(f"{name}: feature provenance is unsafe")
    if not labels.get("plan_hash") == physical.get("plan_hash") == features.get(
        "plan_hash"
    ):
        raise RuntimeError(f"{name}: plan hashes differ")
    if candidate_head.physical_npv_weight != 0.0 or (
        reference_head.physical_npv_weight != 0.0
    ):
        raise RuntimeError(f"{name}: audit heads must contain only direct NPV")
    identities = features.get("identities")
    matrix = features.get("features")
    if not isinstance(identities, list) or not isinstance(matrix, torch.Tensor):
        raise RuntimeError(f"{name}: feature population is incomplete")
    keep = [
        index
        for index, identity in enumerate(identities)
        if identity.get("family") != "BASELINE"
    ]
    scenario_ids = [identities[index]["scenario_id"] for index in keep]
    if len(scenario_ids) != 80 or len(set(scenario_ids)) != 80:
        raise RuntimeError(f"{name}: expected 80 unique non-baseline schedules")
    physical_rows = {row["scenario_id"]: row for row in physical.get("rows", ())}
    label_rows = labels.get("rows")
    if not isinstance(label_rows, dict) or set(scenario_ids) - set(label_rows):
        raise RuntimeError(f"{name}: labels do not cover feature population")
    candidate_direct = candidate_head.predict_vectors(matrix)[keep].numpy()
    reference_direct = reference_head.predict_vectors(matrix)[keep].numpy()
    actual = np.asarray([label_rows[item]["npv_rub"] for item in scenario_ids])
    physical_npv = np.asarray(
        [physical_rows[item]["physical_npv_rub"] for item in scenario_ids]
    )
    reference = (
        (1.0 - REFERENCE_PHYSICAL_WEIGHT) * reference_direct
        + REFERENCE_PHYSICAL_WEIGHT * physical_npv
    )
    arrays = (actual, candidate_direct, reference_direct, physical_npv, reference)
    if not all(np.isfinite(item).all() for item in arrays):
        raise RuntimeError(f"{name}: non-finite disclosed values")
    return {
        "name": name,
        "actual": actual,
        "candidate_direct": candidate_direct,
        "physical": physical_npv,
        "reference": reference,
        "families": [physical_rows[item]["family"] for item in scenario_ids],
        "candidate_head_version": candidate_head.version,
        "reference_head_version": reference_head.version,
        "plan_hash": labels["plan_hash"],
        "input_sha256": {
            "labels": _sha256(labels_path),
            "physical": _sha256(physical_path),
            "features": _sha256(features_path),
            "candidate_head": _sha256(candidate_head_path),
            "reference_head": _sha256(reference_head_path),
        },
    }


def _prediction(split: dict, weight: float) -> np.ndarray:
    return (
        (1.0 - weight) * split["candidate_direct"]
        + weight * split["physical"]
    )


def main() -> int:
    args = _parser().parse_args()
    splits = [
        _load_split(
            name,
            labels_path=getattr(args, f"{name}_labels"),
            physical_path=getattr(args, f"{name}_physical"),
            features_path=getattr(args, f"{name}_features"),
            candidate_head_path=getattr(args, f"{name}_candidate_head"),
            reference_head_path=getattr(args, f"{name}_reference_head"),
        )
        for name in SPLITS
    ]
    reference_metrics = {
        split["name"]: _metrics(split["actual"], split["reference"])
        for split in splits
    }
    candidates = []
    for weight in WEIGHTS:
        metrics = {
            split["name"]: _metrics(split["actual"], _prediction(split, weight))
            for split in splits
        }
        mae_improved_splits = sum(
            metrics[name]["mae_rub"] < reference_metrics[name]["mae_rub"]
            for name in SPLITS
        )
        mean_mae = float(np.mean([metrics[name]["mae_rub"] for name in SPLITS]))
        reference_mean_mae = float(
            np.mean([reference_metrics[name]["mae_rub"] for name in SPLITS])
        )
        feasible = (
            mean_mae < reference_mean_mae
            and mae_improved_splits >= 2
            and all(
                metrics[name]["mae_rub"]
                <= reference_metrics[name]["mae_rub"] + MAX_MAE_REGRESSION_RUB
                and metrics[name]["rank_of_true_best"] <= 5
                and _at_5(metrics[name])
                >= _at_5(reference_metrics[name])
                + PRECISION_AT_5_DIFFERENCE_MIN
                and metrics[name]["ranking"]["spearman_rank_correlation"]
                >= reference_metrics[name]["ranking"]["spearman_rank_correlation"]
                + SPEARMAN_DIFFERENCE_MIN
                for name in SPLITS
            )
        )
        candidates.append(
            {
                "physical_weight": weight,
                "direct_weight": 1.0 - weight,
                "feasible_optimizer_gate_both_splits": feasible,
                "feasible_optimizer_gate_all_splits": feasible,
                "mae_improved_splits": mae_improved_splits,
                "mean_mae_rub": mean_mae,
                "mean_mae_improvement_rub": reference_mean_mae - mean_mae,
                "worst_true_best_rank": max(
                    metrics[name]["rank_of_true_best"] for name in SPLITS
                ),
                "metrics": metrics,
            }
        )
    feasible = [
        item for item in candidates if item["feasible_optimizer_gate_all_splits"]
    ]
    if not feasible:
        raise RuntimeError("no v6 blend satisfies all disclosed transfer gates")
    selected = min(
        feasible,
        key=lambda item: (item["mean_mae_rub"], item["physical_weight"]),
    )
    selected_weight = selected["physical_weight"]
    bootstrap = {}
    for split in splits:
        predicted = _prediction(split, selected_weight)
        rows = [
            {
                "family": family,
                "actual_npv_rub": float(actual),
                "v2_npv_rub": float(reference),
                "v3_npv_rub": float(candidate),
            }
            for family, actual, reference, candidate in zip(
                split["families"],
                split["actual"],
                split["reference"],
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
        "selection_design": "three-way leave-one-blind-out v6 transfer",
        "reference": {
            "name": "cross-fitted production v5 procedure",
            "physical_weight": REFERENCE_PHYSICAL_WEIGHT,
            "metrics": reference_metrics,
            "mean_mae_rub": float(
                np.mean([reference_metrics[name]["mae_rub"] for name in SPLITS])
            ),
        },
        "weight_grid": list(WEIGHTS),
        "selection_rule": {
            "require_mean_mae_improvement": True,
            "require_mae_improvement_on_at_least_splits": 2,
            "max_mae_regression_each_split_rub": MAX_MAE_REGRESSION_RUB,
            "require_true_best_rank_max_each_split": 5,
            "precision_at_5_difference_min_each_split": (
                PRECISION_AT_5_DIFFERENCE_MIN
            ),
            "spearman_difference_min_each_split": SPEARMAN_DIFFERENCE_MIN,
            "then_minimize_mean_mae_rub": True,
        },
        "splits": {
            split["name"]: {
                "n_scenarios": len(split["actual"]),
                "plan_hash": split["plan_hash"],
                "candidate_head_version": split["candidate_head_version"],
                "reference_head_version": split["reference_head_version"],
                "input_sha256": split["input_sha256"],
            }
            for split in splits
        },
        "candidates": candidates,
        "selected": selected,
        "selected_bootstrap_vs_reference": bootstrap,
    }
    _write_json(args.output, report)
    print(
        f"selected v6 physical weight={selected_weight:g}; "
        f"mean MAE improvement={selected['mean_mae_improvement_rub'] / 1e6:.3f}m",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
