"""Select and fit a direct scenario-level NPV surrogate without test leakage."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import asdict
from pathlib import Path

import torch
from torch import Tensor

from surrogate.metrics import ranking_metrics
from surrogate.npv_head import (
    ScenarioNpvHead,
    _kernel,
    scenario_feature_vector,
)

FEATURE_WIDTHS = {"global": 84, "temporal": 1260, "full": 2908, "economic": 4406}
RIDGES = (1.0e-5, 1.0e-4, 1.0e-3, 1.0e-2, 1.0e-1, 1.0, 10.0)
RBF_FACTORS = (0.1, 0.3, 1.0, 3.0, 10.0)
SPEARMAN_EQUIVALENCE = 0.02


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _features_for_bucket(blob: dict, bucket: str) -> Tensor:
    x, well_index, _ = blob["tensors"][bucket]
    counts = blob["counts"][bucket]
    vectors = []
    offset = 0
    for index, count in enumerate(counts, start=1):
        stop = offset + count
        vectors.append(
            scenario_feature_vector(
                x[offset:stop],
                well_index[offset:stop],
                n_wells=len(blob["wells"]),
                feature_set="well_temporal",
            )
        )
        offset = stop
        if index == 1 or index % 25 == 0 or index == len(counts):
            print(f"{bucket}: features {index}/{len(counts)}", flush=True)
    if offset != len(x):
        raise RuntimeError(f"{bucket}: node counts не покрывают tensor")
    return torch.stack(vectors)


def _targets(labels: dict, identities: list[dict], bucket: str) -> Tensor:
    values = []
    for identity in identities:
        key = f"{identity['source_dataset']}:{identity['scenario_id']}"
        row = labels["rows"].get(key)
        if row is None:
            raise RuntimeError(f"нет NPV label для {key}")
        if row["bucket"] != bucket:
            raise RuntimeError(f"{key}: label bucket изменился")
        if row["canonical_schedule_hash"] != identity["canonical_schedule_hash"]:
            raise RuntimeError(f"{key}: schedule hash label не совпадает")
        values.append(float(row["npv_rub"]))
    return torch.tensor(values, dtype=torch.float64)


def _score(actual: Tensor, predicted: Tensor) -> dict:
    actual_values = actual.tolist()
    predicted_values = predicted.tolist()
    actual_mean = statistics.mean(actual_values)
    predicted_mean = statistics.mean(predicted_values)
    actual_variance = math.fsum((value - actual_mean) ** 2 for value in actual_values)
    covariance = math.fsum(
        (fact - actual_mean) * (estimate - predicted_mean)
        for fact, estimate in zip(actual_values, predicted_values)
    )
    actual_order = sorted(
        range(len(actual_values)), key=lambda index: (-actual_values[index], index)
    )
    predicted_order = sorted(
        range(len(predicted_values)),
        key=lambda index: (-predicted_values[index], index),
    )
    residual = [
        estimate - fact for fact, estimate in zip(actual_values, predicted_values)
    ]
    return {
        "ranking": asdict(
            ranking_metrics(
                actual_values,
                predicted_values,
                k_values=(1, 3, 5, 10, 20, 26, 40),
            )
        ),
        "rank_of_true_best": predicted_order.index(actual_order[0]) + 1,
        "mae_rub": statistics.mean(abs(value) for value in residual),
        "bias_rub": predicted_mean - actual_mean,
        "slope_predicted_on_actual": covariance / actual_variance,
        "sd_ratio": statistics.pstdev(predicted_values)
        / statistics.pstdev(actual_values),
    }


def _feature_view(full: Tensor, feature_set: str) -> Tensor:
    if feature_set == "well_temporal":
        return full
    return full[:, : FEATURE_WIDTHS[feature_set]]


def _standardize(train: Tensor, other: Tensor) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    mean = train.mean(dim=0)
    scale = train.std(dim=0, unbiased=False)
    scale = torch.where(scale > 1.0e-10, scale, torch.ones_like(scale))
    return (train - mean) / scale, (other - mean) / scale, mean, scale


def _squared_distances(left: Tensor, right: Tensor) -> Tensor:
    return (
        left.square().sum(dim=1, keepdim=True)
        + right.square().sum(dim=1).unsqueeze(0)
        - 2.0 * left @ right.T
    ).clamp_min(0.0)


def _kernel_path(
    train: Tensor,
    validation: Tensor,
    target: Tensor,
    *,
    kernel: str,
    gamma: float,
) -> Tensor:
    gram = _kernel(train, train, kernel, gamma)
    gram = (gram + gram.T) * 0.5
    eigenvalues, eigenvectors = torch.linalg.eigh(gram)
    eigenvalues = eigenvalues.clamp_min(0.0)
    projected = eigenvectors.T @ target
    ridge = torch.tensor(RIDGES, dtype=torch.float64)
    dual = eigenvectors @ (projected[:, None] / (eigenvalues[:, None] + ridge))
    return _kernel(validation, train, kernel, gamma) @ dual


def _select(
    train_full: Tensor,
    validation_full: Tensor,
    train_target: Tensor,
    validation_target: Tensor,
) -> tuple[list[dict], dict]:
    target_mean = float(train_target.mean())
    target_scale = float(train_target.std(unbiased=False))
    normalized_target = (train_target - target_mean) / target_scale
    candidates = []
    for feature_set in ("global", "temporal", "full", "well_temporal"):
        train, validation, _, _ = _standardize(
            _feature_view(train_full, feature_set),
            _feature_view(validation_full, feature_set),
        )
        train_distances = _squared_distances(train, train)
        positive = train_distances[train_distances > 1.0e-12]
        median_distance = float(positive.median())
        specs = [("linear", 1.0, None), ("poly2", 1.0, None)]
        specs.extend(
            ("rbf", factor / median_distance, factor) for factor in RBF_FACTORS
        )
        for kernel, gamma, factor in specs:
            path = _kernel_path(
                train,
                validation,
                normalized_target,
                kernel=kernel,
                gamma=gamma,
            )
            for ridge_index, ridge in enumerate(RIDGES):
                predicted = target_mean + target_scale * path[:, ridge_index]
                candidate_id = (
                    f"{feature_set}-{kernel}-"
                    f"{factor if factor is not None else 'na'}-{ridge:g}"
                )
                item = {
                    "candidate_id": candidate_id,
                    "feature_set": feature_set,
                    "kernel": kernel,
                    "gamma": gamma,
                    "gamma_factor": factor,
                    "ridge": ridge,
                    "validation": _score(validation_target, predicted),
                }
                candidates.append(item)
                print(
                    f"{candidate_id}: "
                    f"rho={item['validation']['ranking']['spearman_rank_correlation']:.4f}; "
                    f"MAE={item['validation']['mae_rub'] / 1e6:.2f}m; "
                    f"champion={item['validation']['rank_of_true_best']}",
                    flush=True,
                )
    best_rho = max(
        item["validation"]["ranking"]["spearman_rank_correlation"]
        for item in candidates
    )
    equivalent = [
        item
        for item in candidates
        if item["validation"]["ranking"]["spearman_rank_correlation"]
        >= best_rho - SPEARMAN_EQUIVALENCE
    ]
    winner = min(
        equivalent,
        key=lambda item: (
            item["validation"]["mae_rub"],
            item["validation"]["rank_of_true_best"],
            -item["validation"]["ranking"]["spearman_rank_correlation"],
            item["candidate_id"],
        ),
    )
    return candidates, winner


def _fit_final(
    train_full: Tensor,
    target: Tensor,
    winner: dict,
    *,
    wells: tuple[str, ...],
    static_feature_names: tuple[str, ...],
    dataset_hash: str,
    calibration_slope: float = 1.0,
    calibration_intercept_rub: float = 0.0,
    target_provenance_hash: str = "",
    feature_provenance_hash: str = "",
    feature_context_sha256: str = "",
) -> ScenarioNpvHead:
    raw = _feature_view(train_full, winner["feature_set"])
    mean = raw.mean(dim=0)
    scale = raw.std(dim=0, unbiased=False)
    scale = torch.where(scale > 1.0e-10, scale, torch.ones_like(scale))
    centers = (raw - mean) / scale
    target_mean = float(target.mean())
    target_scale = float(target.std(unbiased=False))
    normalized_target = (target - target_mean) / target_scale
    gamma = 1.0
    if winner["kernel"] == "rbf":
        distances = _squared_distances(centers, centers)
        positive = distances[distances > 1.0e-12]
        gamma = winner["gamma_factor"] / float(positive.median())
    gram = _kernel(centers, centers, winner["kernel"], gamma)
    gram = (gram + gram.T) * 0.5
    gram.diagonal().add_(winner["ridge"])
    dual = torch.linalg.solve(gram, normalized_target)
    return ScenarioNpvHead(
        wells=wells,
        static_feature_names=static_feature_names,
        feature_set=winner["feature_set"],
        kernel=winner["kernel"],
        gamma=gamma,
        feature_mean=mean,
        feature_scale=scale,
        centers=centers,
        dual=dual,
        target_mean_rub=target_mean,
        target_scale_rub=target_scale,
        dataset_hash=dataset_hash,
        target_provenance_hash=target_provenance_hash,
        feature_provenance_hash=feature_provenance_hash,
        feature_context_sha256=feature_context_sha256,
        calibration_slope=calibration_slope,
        calibration_intercept_rub=calibration_intercept_rub,
    )


def _oof_calibration(
    full: Tensor,
    target: Tensor,
    winner: dict,
    *,
    wells: tuple[str, ...],
    static_feature_names: tuple[str, ...],
    dataset_hash: str,
    folds: int = 5,
) -> tuple[float, float, dict, dict]:
    generator = torch.Generator().manual_seed(20260826)
    permutation = torch.randperm(len(target), generator=generator)
    predicted = torch.empty_like(target)
    for fold in range(folds):
        held_out = permutation[fold::folds]
        mask = torch.ones(len(target), dtype=torch.bool)
        mask[held_out] = False
        head = _fit_final(
            full[mask],
            target[mask],
            winner,
            wells=wells,
            static_feature_names=static_feature_names,
            dataset_hash=dataset_hash,
        )
        held_out_raw = _feature_view(full[held_out], winner["feature_set"])
        predicted[held_out] = head.predict_vectors_raw(held_out_raw)
        print(f"OOF calibration fold {fold + 1}/{folds}", flush=True)
    predicted_mean = predicted.mean()
    target_mean = target.mean()
    variance = (predicted - predicted_mean).square().sum()
    slope = float(
        ((predicted - predicted_mean) * (target - target_mean)).sum() / variance
    )
    if not math.isfinite(slope) or slope <= 0.0:
        raise RuntimeError("OOF calibration дала неположительный slope")
    intercept = float(target_mean - slope * predicted_mean)
    calibrated = intercept + slope * predicted
    return slope, intercept, _score(target, predicted), _score(target, calibrated)


def main() -> int:
    args = _parser().parse_args()
    started = time.monotonic()
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if labels.get("format") != "aios.surrogate-npv-labels.v1":
        raise RuntimeError("неподдержанный labels artifact")
    if len(labels.get("rows", {})) != 700:
        raise RuntimeError("NPV labels ещё не завершены")
    print(f"загрузка {args.tensors}", flush=True)
    blob = torch.load(
        args.tensors,
        map_location="cpu",
        weights_only=False,
        mmap=True,
    )
    if blob.get("format") != "aios.surrogate-tensors.v2":
        raise RuntimeError("неподдержанный tensor artifact")
    if labels["dataset_hash"] != blob["dataset_hash"]:
        raise RuntimeError("dataset_hash tensors/labels не совпадает")

    train_full = _features_for_bucket(blob, "train")
    validation_full = _features_for_bucket(blob, "validation")
    train_target = _targets(labels, blob["identities"]["train"], "train")
    validation_target = _targets(labels, blob["identities"]["validation"], "validation")
    candidates, winner = _select(
        train_full,
        validation_full,
        train_target,
        validation_target,
    )
    selection_report = {
        "format": "aios.surrogate-npv-head-selection.v1",
        "dataset_hash": blob["dataset_hash"],
        "selection_data": ["train", "validation"],
        "test_read_during_selection": False,
        "selection_rule": {
            "spearman_equivalence_band": SPEARMAN_EQUIVALENCE,
            "within_band_minimize": [
                "mae_rub",
                "rank_of_true_best",
                "negative_spearman",
                "candidate_id",
            ],
        },
        "candidate_count": len(candidates),
        "winner": winner,
        "candidates": candidates,
    }
    _write_json(args.output_dir / "selection_report.json", selection_report)
    print(
        f"LOCKED winner: {winner['candidate_id']}; test ещё не прочитан",
        flush=True,
    )

    combined_full = torch.cat((train_full, validation_full))
    combined_target = torch.cat((train_target, validation_target))
    calibration_slope, calibration_intercept, oof_raw, oof_calibrated = (
        _oof_calibration(
            combined_full,
            combined_target,
            winner,
            wells=tuple(blob["wells"]),
            static_feature_names=tuple(blob["static_names"]),
            dataset_hash=blob["dataset_hash"],
        )
    )
    calibration_applied = oof_calibrated["mae_rub"] < oof_raw["mae_rub"]
    if not calibration_applied:
        calibration_slope = 1.0
        calibration_intercept = 0.0
    head = _fit_final(
        combined_full,
        combined_target,
        winner,
        wells=tuple(blob["wells"]),
        static_feature_names=tuple(blob["static_names"]),
        dataset_hash=blob["dataset_hash"],
        calibration_slope=calibration_slope,
        calibration_intercept_rub=calibration_intercept,
    )
    checkpoint = head.save(args.output_dir / "npv_head.pt")

    # This is deliberately below winner persistence and final fitting: test cannot
    # influence model-family, feature-set, kernel, gamma-factor, or ridge selection.
    test_full = _features_for_bucket(blob, "test")
    test_target = _targets(labels, blob["identities"]["test"], "test")
    test_raw = _feature_view(test_full, head.feature_set)
    test_raw_predicted = head.predict_vectors_raw(test_raw)
    test_predicted = head.predict_vectors(test_raw)
    test_metrics = _score(test_target, test_predicted)
    report = {
        **selection_report,
        "format": "aios.surrogate-npv-head-training-report.v1",
        "tensor_artifact": str(args.tensors),
        "labels_artifact": str(args.labels),
        "checkpoint": checkpoint.name,
        "model_version": head.version,
        "final_fit_data": ["train", "validation"],
        "oof_calibration": {
            "folds": 5,
            "applied": calibration_applied,
            "slope": calibration_slope,
            "intercept_rub": calibration_intercept,
            "raw_metrics": oof_raw,
            "calibrated_metrics": oof_calibrated,
        },
        "raw_test_metrics": _score(test_target, test_raw_predicted),
        "test_metrics": test_metrics,
        "seconds": time.monotonic() - started,
    }
    _write_json(args.output_dir / "training_report.json", report)
    print(
        f"TEST once: rho={test_metrics['ranking']['spearman_rank_correlation']:.4f}; "
        f"MAE={test_metrics['mae_rub'] / 1e6:.2f}m; "
        f"champion={test_metrics['rank_of_true_best']}",
        flush=True,
    )
    print(f"готово: {checkpoint}; version={head.version}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
