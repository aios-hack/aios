"""Search block-balanced NPV kernels on train+validation grouped OOF only."""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import GroupKFold

if __package__:
    from tools.surrogate_benchmark_npv_models import (
        FEATURE_WIDTHS,
        _load_selection_data,
        _metrics,
        _write_json,
    )
else:
    from surrogate_benchmark_npv_models import (
        FEATURE_WIDTHS,
        _load_selection_data,
        _metrics,
        _write_json,
    )

BLOCKS = {
    "global": (0, FEATURE_WIDTHS["global"]),
    "temporal": (FEATURE_WIDTHS["global"], FEATURE_WIDTHS["temporal"]),
    "well": (FEATURE_WIDTHS["temporal"], FEATURE_WIDTHS["full"]),
    "well_temporal": (FEATURE_WIDTHS["full"], FEATURE_WIDTHS["well_temporal"]),
}
RIDGES = (0.03, 0.1, 0.3, 1.0, 3.0)
SELECTION_BAND = 0.02


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260826)
    return parser


def _weight_specs() -> list[dict[str, float]]:
    specs: list[dict[str, float]] = []
    # The first row reproduces the implicit dimensional weighting of v2.
    specs.append(
        {
            "global": 84 / 2908,
            "temporal": 1176 / 2908,
            "well": 1648 / 2908,
            "well_temporal": 0.0,
        }
    )
    for global_weight, temporal_weight, extra_weight in itertools.product(
        (0.0, 0.03, 0.08, 0.15, 0.25),
        (0.10, 0.25, 0.40, 0.55, 0.70),
        (0.0, 0.02, 0.05, 0.10),
    ):
        well_weight = 1.0 - global_weight - temporal_weight - extra_weight
        if well_weight < 0.05:
            continue
        specs.append(
            {
                "global": global_weight,
                "temporal": temporal_weight,
                "well": well_weight,
                "well_temporal": extra_weight,
            }
        )
    unique = {}
    for item in specs:
        key = tuple(round(item[name], 12) for name in BLOCKS)
        unique[key] = item
    return list(unique.values())


def _standardized_dot_blocks(
    matrix: np.ndarray,
    train: np.ndarray,
    held_out: np.ndarray,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    result = {}
    for name, (start, stop) in BLOCKS.items():
        fit = matrix[train, start:stop].astype(np.float64, copy=False)
        test = matrix[held_out, start:stop].astype(np.float64, copy=False)
        mean = fit.mean(axis=0)
        scale = fit.std(axis=0)
        active = scale > 1.0e-10
        if not active.any():
            result[name] = (
                np.zeros((len(train), len(train))),
                np.zeros((len(held_out), len(train))),
            )
            continue
        fit = (fit[:, active] - mean[active]) / scale[active]
        test = (test[:, active] - mean[active]) / scale[active]
        width = fit.shape[1]
        result[name] = (fit @ fit.T / width, test @ fit.T / width)
    return result


def _kernel(
    dots: dict[str, tuple[np.ndarray, np.ndarray]],
    weights: dict[str, float],
    *,
    mode: str,
) -> tuple[np.ndarray, np.ndarray]:
    if mode == "joint":
        train = sum(weights[name] * dots[name][0] for name in BLOCKS)
        held_out = sum(weights[name] * dots[name][1] for name in BLOCKS)
        return np.square(1.0 + train), np.square(1.0 + held_out)
    if mode == "additive":
        train = sum(
            weights[name] * np.square(1.0 + dots[name][0]) for name in BLOCKS
        )
        held_out = sum(
            weights[name] * np.square(1.0 + dots[name][1]) for name in BLOCKS
        )
        return train, held_out
    raise ValueError(f"unknown kernel mode {mode!r}")


def _ridge_path(
    gram: np.ndarray,
    cross: np.ndarray,
    target: np.ndarray,
) -> np.ndarray:
    target_mean = target.mean()
    target_scale = target.std()
    normalized = (target - target_mean) / target_scale
    eigenvalues, eigenvectors = np.linalg.eigh((gram + gram.T) * 0.5)
    eigenvalues = np.maximum(eigenvalues, 0.0)
    projected = eigenvectors.T @ normalized
    dual = eigenvectors @ (
        projected[:, None] / (eigenvalues[:, None] + np.asarray(RIDGES))
    )
    return target_mean + target_scale * (cross @ dual)


def _candidate_id(mode: str, weights: dict[str, float], ridge: float) -> str:
    encoded = "-".join(f"{name[:2]}{weights[name]:.3f}" for name in BLOCKS)
    return f"{mode}-{encoded}-a{ridge:g}"


def _winner(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    best_rho = max(
        item["oof"]["ranking"]["spearman_rank_correlation"]
        for item in candidates
    )
    equivalent = [
        item
        for item in candidates
        if item["oof"]["ranking"]["spearman_rank_correlation"]
        >= best_rho - SELECTION_BAND
    ]
    return min(
        equivalent,
        key=lambda item: (
            item["oof"]["mae_rub"],
            item["oof"]["rank_of_true_best"],
            -item["oof"]["ranking"]["spearman_rank_correlation"],
            item["candidate_id"],
        ),
    )


def main() -> int:
    args = _parser().parse_args()
    started = time.monotonic()
    matrix, target, groups, _, dataset_hash = _load_selection_data(
        args.tensors, args.labels, args.feature_cache
    )
    specs = _weight_specs()
    modes = ("joint", "additive")
    candidate_specs = {
        _candidate_id(mode, weights, ridge): (mode, weights, ridge)
        for mode in modes
        for weights in specs
        for ridge in RIDGES
    }
    predictions = {
        candidate_id: np.full(len(target), np.nan)
        for candidate_id in candidate_specs
    }
    fold_metrics: dict[str, list[dict[str, Any]]] = {
        candidate_id: [] for candidate_id in predictions
    }
    splitter = GroupKFold(
        n_splits=args.folds, shuffle=True, random_state=args.seed
    )
    for fold, (train, held_out) in enumerate(
        splitter.split(matrix, target, groups), start=1
    ):
        if set(groups[train]) & set(groups[held_out]):
            raise RuntimeError("group leakage detected")
        dots = _standardized_dot_blocks(matrix, train, held_out)
        for mode in modes:
            for spec_index, weights in enumerate(specs, start=1):
                gram, cross = _kernel(dots, weights, mode=mode)
                path = _ridge_path(gram, cross, target[train])
                for ridge_index, ridge in enumerate(RIDGES):
                    candidate_id = _candidate_id(mode, weights, ridge)
                    predictions[candidate_id][held_out] = path[:, ridge_index]
                    fold_metrics[candidate_id].append(
                        {
                            "fold": fold,
                            "metrics": _metrics(
                                target[held_out], path[:, ridge_index]
                            ),
                        }
                    )
                if spec_index % 20 == 0:
                    print(
                        f"fold {fold}/{args.folds} {mode} "
                        f"weights {spec_index}/{len(specs)}",
                        flush=True,
                    )
        print(f"fold {fold}/{args.folds} complete", flush=True)

    candidates = []
    for candidate_id, predicted in predictions.items():
        if not np.isfinite(predicted).all():
            raise RuntimeError(f"incomplete OOF prediction for {candidate_id}")
        mode, weights, ridge = candidate_specs[candidate_id]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "mode": mode,
                "weights": weights,
                "ridge": ridge,
                "oof": _metrics(target, predicted),
                "folds": fold_metrics[candidate_id],
            }
        )
    candidates.sort(
        key=lambda item: (
            -item["oof"]["ranking"]["spearman_rank_correlation"],
            item["oof"]["mae_rub"],
        )
    )
    report = {
        "format": "aios.surrogate-npv-block-kernel-screen.v1",
        "dataset_hash": dataset_hash,
        "selection_buckets": ["train", "validation"],
        "locked_test_read": False,
        "group_key": "canonical_schedule_hash",
        "n_rows": len(target),
        "n_groups": len(set(groups)),
        "folds": args.folds,
        "seed": args.seed,
        "weight_spec_count": len(specs),
        "candidate_count": len(candidates),
        "winner": _winner(candidates),
        "top_candidates": candidates[:100],
        "seconds": time.monotonic() - started,
    }
    _write_json(args.output, report)
    winner = report["winner"]
    print(
        f"winner {winner['candidate_id']}: "
        f"rho={winner['oof']['ranking']['spearman_rank_correlation']:.4f}; "
        f"MAE={winner['oof']['mae_rub'] / 1e6:.2f}m",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
