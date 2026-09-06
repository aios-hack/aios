"""Fit one pre-selected NPV head on train+validation without touching test."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from contracts import canonical_bytes
from surrogate.npv_block_head import (
    LEGACY_IMPLEMENTATION_HASHES,
    block_implementation_hash,
    fit_block_head,
    load_direct_npv_head,
)
from surrogate.npv_head import feature_implementation_hash
from surrogate.npv_target import validate_target_provenance

if __package__:
    from tools.surrogate_benchmark_npv_models import (
        BLOCK_SHORTLIST_PROVENANCE,
        SELECTION_RULE,
        _deployable_spec,
        _factories,
        _apply_calibration,
        _cv_predict,
        _linear_calibration,
        _metrics,
        _validate_selection_labels,
        _unique_schedule_population,
        _view,
        _winner,
        screen_implementation_hash,
        screen_runtime_versions,
    )
    from tools.surrogate_train_npv_head import _fit_final
else:
    from surrogate_benchmark_npv_models import (
        BLOCK_SHORTLIST_PROVENANCE,
        SELECTION_RULE,
        _deployable_spec,
        _factories,
        _apply_calibration,
        _cv_predict,
        _linear_calibration,
        _metrics,
        _validate_selection_labels,
        _unique_schedule_population,
        _view,
        _winner,
        screen_implementation_hash,
        screen_runtime_versions,
    )
    from surrogate_train_npv_head import _fit_final


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--screen-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidate-id")
    parser.add_argument(
        "--augmentation-features", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--augmentation-labels", type=Path, action="append", default=[]
    )
    return parser


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_locked_inputs(
    screen: dict, *, tensors: Path | None, labels: Path, feature_cache: Path
) -> None:
    expected = screen.get("input_artifacts")
    required = {"labels", "feature_cache"} | ({"tensors"} if tensors else set())
    if not isinstance(expected, dict) or set(expected) != required:
        raise RuntimeError("screen does not pin all training input artifacts")
    inputs = [("labels", labels), ("feature_cache", feature_cache)]
    if tensors is not None:
        inputs.append(("tensors", tensors))
    for name, path in inputs:
        item = expected[name]
        if not isinstance(item, dict) or item.get("sha256") != _sha256(path):
            raise RuntimeError(f"{name} differs from frozen model screen")


def _locked_winner(screen: dict, requested_id: str | None) -> tuple[dict, dict]:
    if (
        screen.get("format") != "aios.surrogate-npv-model-screen.v2"
        or screen.get("status") != "complete"
    ):
        raise RuntimeError("screen must be a finalized v2 report")
    if screen.get("completed_candidates") != screen.get("candidate_count"):
        raise RuntimeError("screen candidate population is incomplete")
    if screen.get("selection_rule") != SELECTION_RULE:
        raise RuntimeError("screen selection rule differs from audited policy")
    if screen.get("block_shortlist_provenance") != BLOCK_SHORTLIST_PROVENANCE:
        raise RuntimeError("screen block shortlist differs from frozen provenance")
    if screen.get("screen_implementation_sha256") != screen_implementation_hash():
        raise RuntimeError("screen implementation differs from frozen report")
    if screen.get("block_implementation_sha256") not in {
        block_implementation_hash(),
        *LEGACY_IMPLEMENTATION_HASHES,
    }:
        raise RuntimeError("block runtime differs from frozen screen")
    if screen.get("runtime_versions") != screen_runtime_versions():
        raise RuntimeError("numerical runtime differs from frozen screen")
    seed = screen.get("seed")
    trees = screen.get("trees")
    candidates = screen.get("candidates")
    if (
        type(seed) is not int
        or type(trees) is not int
        or trees < 1
        or not isinstance(candidates, list)
    ):
        raise RuntimeError("screen candidate population is not reproducible")
    expected_ids = list(_factories(seed=seed, trees=trees))
    candidate_ids = [item.get("candidate_id") for item in candidates]
    if (
        candidate_ids != expected_ids
        or len(set(candidate_ids)) != len(candidate_ids)
        or screen.get("candidate_count") != len(expected_ids)
        or screen.get("completed_candidates") != len(expected_ids)
    ):
        raise RuntimeError("screen candidate population differs from frozen search")
    expected_winner = _winner(candidates)
    if screen.get("winner") != expected_winner:
        raise RuntimeError("screen overall winner is inconsistent with candidates")
    deployable_candidates = [
        item for item in candidates if _deployable_spec(str(item["candidate_id"]))
    ]
    expected_deployable = _winner(deployable_candidates)
    if screen.get("deployable_winner") != expected_deployable:
        raise RuntimeError("screen deployable winner is inconsistent with candidates")
    nested = screen.get("nested_deployable_selection")
    if not isinstance(nested, dict) or nested.get("protocol") != (
        "repeated_nested_group_cv_v2"
    ):
        raise RuntimeError("screen lacks honest nested grouped-CV evaluation")
    expected_deployable_ids = [item["candidate_id"] for item in deployable_candidates]
    expected_nested_folds = screen.get("outer_folds")
    expected_nested_repeats = screen.get("outer_repeats")
    winner_counts = nested.get("winner_counts")
    if (
        nested.get("selection_candidates") != expected_deployable_ids
        or nested.get("selection_rule") != SELECTION_RULE
        or nested.get("inner_folds") != screen.get("folds")
        or nested.get("outer_folds") != expected_nested_folds
        or nested.get("outer_repeats") != expected_nested_repeats
        or nested.get("seed") != screen.get("seed")
        or type(expected_nested_folds) is not int
        or type(expected_nested_repeats) is not int
        or not isinstance(winner_counts, dict)
        or not set(winner_counts) <= set(expected_deployable_ids)
        or any(
            type(value) is not int or value < 1
            for value in winner_counts.values()
        )
        or sum(winner_counts.values())
        != expected_nested_folds * expected_nested_repeats
        or len(nested.get("folds", ()))
        != expected_nested_folds * expected_nested_repeats
        or len(nested.get("repeat_metrics", ())) != expected_nested_repeats
        or not isinstance(nested.get("averaged_oof"), dict)
        or any(
            not isinstance(fold, dict)
            or fold.get("selected_candidate_id") not in expected_deployable_ids
            for fold in nested.get("folds", ())
        )
    ):
        raise RuntimeError("nested screen candidate population differs")
    selected = screen.get("deployable_winner")
    if not isinstance(selected, dict):
        raise TypeError("screen lacks a deployable winner")
    candidate_id = selected.get("candidate_id")
    if requested_id is not None and requested_id != candidate_id:
        raise RuntimeError("requested candidate differs from frozen screen winner")
    expected_spec = _deployable_spec(str(candidate_id))
    if expected_spec is None or selected.get("deployable_spec") != expected_spec:
        raise RuntimeError("deployable winner is not representable by ScenarioNpvHead")
    winner = {"candidate_id": candidate_id, **expected_spec}
    return winner, selected


def _locked_calibration(screen: dict, candidate_id: str) -> tuple[float, float]:
    calibration = screen.get("deployable_calibration")
    if (
        not isinstance(calibration, dict)
        or calibration.get("candidate_id") != candidate_id
        or calibration.get("method")
        not in {
            "grouped_oof_ols_v1",
            "grouped_oof_median_bias_v1",
            "identity_degenerate",
            "identity_nonpositive",
            "identity_no_mae_gain",
        }
        or type(calibration.get("oof_repeats")) is not int
        or calibration["oof_repeats"] < 1
        or not isinstance(calibration.get("raw_averaged_oof"), dict)
        or not isinstance(calibration.get("calibrated_oof"), dict)
    ):
        raise RuntimeError("screen calibration does not belong to frozen winner")
    slope = calibration.get("slope")
    intercept = calibration.get("intercept_rub")
    if (
        type(slope) not in (int, float)
        or type(intercept) not in (int, float)
        or not math.isfinite(float(slope))
        or not math.isfinite(float(intercept))
        or float(slope) <= 0.0
    ):
        raise RuntimeError("screen calibration is invalid")
    return float(slope), float(intercept)


def _load_augmentation(
    features_path: Path,
    labels_path: Path,
    *,
    target_provenance_hash: str,
    feature_context_sha256: str,
    feature_width: int,
    historical_schedule_hashes: set[str],
) -> tuple[torch.Tensor, torch.Tensor, list[dict], str, list[dict[str, str]]]:
    features = torch.load(features_path, map_location="cpu", weights_only=False)
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    identities = features.get("identities")
    rows = labels.get("rows")
    if (
        features.get("format") != "aios.surrogate-blind-npv-features.v2"
        or features.get("response_data_read") is not False
        or features.get("historical_test_read") is not False
        or features.get("feature_set") != "economic"
        or features.get("feature_provenance_hash") != feature_implementation_hash()
        or features.get("feature_context_sha256") != feature_context_sha256
        or not isinstance(identities, list)
        or len(identities) != 81
    ):
        raise RuntimeError("blind1 augmentation feature provenance differs")
    if (
        labels.get("format") != "aios.surrogate-disclosed-blind-npv-labels.v1"
        or labels.get("historical_test_read") is not False
        or labels.get("blind_response_read_after_final_audit") is not True
        or labels.get("fit_population_role")
        != "augmentation_after_frozen_hyperparameter_selection"
        or labels.get("expected_rows") != 81
        or not isinstance(rows, dict)
        or len(rows) != 81
        or labels.get("target_provenance", {}).get("target_provenance_sha256")
        != target_provenance_hash
        or labels.get("plan_hash") != features.get("plan_hash")
    ):
        raise RuntimeError("blind1 augmentation label provenance differs")
    if validate_target_provenance(labels.get("target_provenance")) != (
        target_provenance_hash
    ):
        raise RuntimeError("blind1 augmentation target provenance differs")
    matrix = features.get("features")
    if not isinstance(matrix, torch.Tensor) or matrix.shape != (81, feature_width):
        raise RuntimeError("blind1 augmentation feature matrix differs")
    if not bool(torch.isfinite(matrix).all()):
        raise RuntimeError("blind1 augmentation features are non-finite")
    targets = []
    schedule_hashes = set()
    selected_indices = []
    selected_identities = []
    excluded = []
    for index, identity in enumerate(identities):
        scenario_id = identity["scenario_id"]
        row = rows.get(scenario_id)
        if not isinstance(row, dict) or (
            row.get("family") != identity.get("family")
            or row.get("canonical_schedule_hash")
            != identity.get("canonical_schedule_hash")
        ):
            raise RuntimeError(f"{scenario_id}: blind1 augmentation identity differs")
        schedule_hash = identity["canonical_schedule_hash"]
        target = float(row["npv_rub"])
        if not math.isfinite(target):
            raise RuntimeError(
                f"{scenario_id}: blind1 augmentation target is non-finite"
            )
        if schedule_hash in historical_schedule_hashes:
            excluded.append(
                {
                    "scenario_id": scenario_id,
                    "canonical_schedule_hash": schedule_hash,
                    "reason": "historical_schedule_overlap",
                }
            )
            continue
        if schedule_hash in schedule_hashes:
            excluded.append(
                {
                    "scenario_id": scenario_id,
                    "canonical_schedule_hash": schedule_hash,
                    "reason": "duplicate_blind_schedule",
                }
            )
            continue
        schedule_hashes.add(schedule_hash)
        selected_indices.append(index)
        selected_identities.append(identity)
        targets.append(target)
    if not selected_indices:
        raise RuntimeError("blind1 augmentation has no new schedules")
    population_hash = hashlib.sha256(
        canonical_bytes(
            {
                "format": "aios.npv-fit-augmentation.v1",
                "feature_sha256": _sha256(features_path),
                "labels_sha256": _sha256(labels_path),
                "target_provenance_hash": target_provenance_hash,
                "schedule_hashes": sorted(schedule_hashes),
                "excluded_schedule_overlaps": excluded,
            }
        )
    ).hexdigest()
    return (
        matrix[selected_indices].to(torch.float64),
        torch.tensor(targets, dtype=torch.float64),
        selected_identities,
        population_hash,
        excluded,
    )


def _refit_population_calibration(
    screen: dict,
    candidate_id: str,
    matrix: np.ndarray,
    target: np.ndarray,
    groups: np.ndarray,
) -> dict:
    """Fit calibration only, with frozen model spec and grouped OOF predictions."""

    folds = screen.get("folds")
    seed = screen.get("seed")
    trees = screen.get("trees")
    repeats = screen.get("deployable_calibration", {}).get("oof_repeats")
    if not all(type(item) is int and item > 0 for item in (folds, repeats, trees)):
        raise RuntimeError("screen calibration protocol is incomplete")
    if type(seed) is not int or folds < 3 or len(set(groups.tolist())) < folds:
        raise RuntimeError("augmented calibration groups are incomplete")
    factories = _factories(seed=seed, trees=trees)
    if candidate_id not in factories:
        raise RuntimeError("frozen calibration candidate is unavailable")
    view = _view(matrix, candidate_id)
    predictions = []
    for repeat in range(repeats):
        predicted, _ = _cv_predict(
            factories[candidate_id],
            view,
            target,
            groups,
            folds=folds,
            seed=seed + 104729 * repeat,
        )
        predictions.append(predicted)
    averaged = np.stack(predictions).mean(axis=0)
    calibration = _linear_calibration(target, averaged)
    calibrated = _apply_calibration(averaged, calibration)
    return {
        **calibration,
        "candidate_id": candidate_id,
        "protocol": "frozen_candidate_repeated_grouped_oof_v1",
        "fit_population_rows": len(target),
        "folds": folds,
        "oof_repeats": repeats,
        "seed": seed,
        "raw_averaged_oof": _metrics(target, averaged),
        "calibrated_oof": _metrics(target, calibrated),
    }


def main() -> int:
    args = _parser().parse_args()
    if len(args.augmentation_features) != len(args.augmentation_labels):
        raise ValueError(
            "each augmentation feature cache requires one matching label artifact"
        )
    if (args.output_dir / "npv_head.pt").exists() or (
        args.output_dir / "lock_report.json"
    ).exists():
        raise FileExistsError("refusing to overwrite a locked NPV candidate")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    _validate_selection_labels(labels)
    screen = json.loads(args.screen_report.read_text(encoding="utf-8"))
    _validate_locked_inputs(
        screen,
        tensors=args.tensors,
        labels=args.labels,
        feature_cache=args.feature_cache,
    )
    cached = torch.load(args.feature_cache, map_location="cpu", weights_only=False)
    blob = (
        torch.load(args.tensors, map_location="cpu", weights_only=False, mmap=True)
        if args.tensors is not None
        else None
    )
    dataset_hash = cached.get("dataset_hash")
    if not labels.get("dataset_hash") == screen.get("dataset_hash") == dataset_hash:
        raise RuntimeError("provenance hashes differ")
    if blob is not None and blob.get("dataset_hash") != dataset_hash:
        raise RuntimeError("tensor/cache dataset hashes differ")
    if blob is None and (
        cached.get("format") != "aios.npv-selection-features.v2"
        or cached.get("response_data_read") is not False
        or cached.get("historical_test_read") is not False
    ):
        raise RuntimeError("tensor-free fit requires safe feature cache v2")
    if (
        cached.get("feature_set") != "economic"
        or cached.get("feature_provenance_hash") != feature_implementation_hash()
        or cached.get("response_data_read") is not False
        or cached.get("historical_test_read") is not False
    ):
        raise RuntimeError("feature cache provenance differs from frozen screen")
    feature_context_sha256 = cached.get("feature_context_sha256")
    if not isinstance(feature_context_sha256, str) or len(feature_context_sha256) != 64:
        raise RuntimeError("feature cache does not pin feature context")
    if screen.get("locked_test_read") is not False or screen.get(
        "selection_buckets"
    ) != ["train", "validation"]:
        raise RuntimeError("screen report may have used the retired test")
    target_provenance_hash = labels["target_provenance"]["target_provenance_sha256"]
    if screen.get("target_provenance_hash") != target_provenance_hash:
        raise RuntimeError("screen/labels target provenance differs")
    if screen.get("feature_provenance_hash") != feature_implementation_hash():
        raise RuntimeError("screen/current feature provenance differs")
    winner, screen_item = _locked_winner(screen, args.candidate_id)
    calibration_slope, calibration_intercept = _locked_calibration(
        screen, winner["candidate_id"]
    )
    identities = cached["identities"]
    if len(identities) != 595 or any(
        item["bucket"] not in {"train", "validation"} for item in identities
    ):
        raise RuntimeError("locked fit must contain exactly train+validation")
    target_values = []
    response_hashes = []
    for item in identities:
        key = f"{item['source_dataset']}:{item['scenario_id']}"
        row = labels["rows"][key]
        if (
            row["bucket"] != item["bucket"]
            or row["canonical_schedule_hash"] != item["canonical_schedule_hash"]
        ):
            raise RuntimeError(f"{key}: locked label identity differs")
        target_values.append(row["npv_rub"])
        response_hashes.append(row["response_hash"])
    target = torch.tensor(target_values, dtype=torch.float64)
    full = cached["features"].to(torch.float64)
    if full.shape != (595, 4406) or not bool(torch.isfinite(full).all()):
        raise RuntimeError("feature cache matrix is invalid")
    if not bool(torch.isfinite(target).all()):
        raise RuntimeError("selection targets contain non-finite values")
    unique_matrix, unique_target, identities = _unique_schedule_population(
        full.numpy(), target.numpy(), identities, response_hashes
    )
    full = torch.from_numpy(unique_matrix).to(torch.float64)
    target = torch.from_numpy(unique_target).to(torch.float64)
    if len(identities) != 593:
        raise RuntimeError("locked fit must contain 593 unique historical schedules")
    identity_sha256 = hashlib.sha256(
        json.dumps(identities, sort_keys=True).encode()
    ).hexdigest()
    if screen.get("identity_sha256") != identity_sha256:
        raise RuntimeError("unique feature population differs from frozen screen")
    historical_fit_population_hash = hashlib.sha256(
        canonical_bytes(
            {
                "format": "aios.npv-historical-fit-population.v1",
                "source_dataset_hash": dataset_hash,
                "target_provenance_hash": target_provenance_hash,
                "labels_sha256": screen["input_artifacts"]["labels"]["sha256"],
                "feature_cache_sha256": screen["input_artifacts"][
                    "feature_cache"
                ]["sha256"],
                "canonical_schedule_hashes": [
                    item["canonical_schedule_hash"] for item in identities
                ],
            }
        )
    ).hexdigest()
    augmentation_reports = []
    augmentation_hashes = []
    fit_dataset_hash = historical_fit_population_hash
    fit_identities = list(identities)
    fit_calibration = screen["deployable_calibration"]
    known_schedule_hashes = {
        item["canonical_schedule_hash"] for item in fit_identities
    }
    for augmentation_features, augmentation_labels in zip(
        args.augmentation_features, args.augmentation_labels, strict=True
    ):
        (
            added_x,
            added_y,
            added_identities,
            augmentation_hash,
            excluded_augmentation,
        ) = _load_augmentation(
            augmentation_features,
            augmentation_labels,
            target_provenance_hash=target_provenance_hash,
            feature_context_sha256=feature_context_sha256,
            feature_width=full.shape[1],
            historical_schedule_hashes=known_schedule_hashes,
        )
        full = torch.cat((full, added_x))
        target = torch.cat((target, added_y))
        fit_identities.extend(added_identities)
        known_schedule_hashes.update(
            item["canonical_schedule_hash"] for item in added_identities
        )
        augmentation_hashes.append(augmentation_hash)
        augmentation_reports.append(
            {
                "features": str(augmentation_features),
                "features_sha256": _sha256(augmentation_features),
                "labels": str(augmentation_labels),
                "labels_sha256": _sha256(augmentation_labels),
                "population_hash": augmentation_hash,
                "n_rows": len(added_identities),
                "excluded_schedule_overlaps": excluded_augmentation,
            }
        )

    if augmentation_hashes:
        if len(augmentation_hashes) == 1:
            fit_dataset_payload = {
                "format": "aios.npv-augmented-fit-population.v1",
                "historical_fit_population_hash": historical_fit_population_hash,
                "augmentation_hash": augmentation_hashes[0],
            }
        else:
            fit_dataset_payload = {
                "format": "aios.npv-augmented-fit-population.v2",
                "historical_fit_population_hash": historical_fit_population_hash,
                "augmentation_hashes": augmentation_hashes,
            }
        fit_dataset_hash = hashlib.sha256(
            canonical_bytes(fit_dataset_payload)
        ).hexdigest()
        fit_calibration = _refit_population_calibration(
            screen,
            winner["candidate_id"],
            full.numpy(),
            target.numpy(),
            np.asarray(
                [item["canonical_schedule_hash"] for item in fit_identities]
            ),
        )
        calibration_slope = float(fit_calibration["slope"])
        calibration_intercept = float(fit_calibration["intercept_rub"])
    wells = tuple(blob["wells"] if blob is not None else cached["wells"])
    static_names = tuple(
        blob["static_names"] if blob is not None else cached["static_names"]
    )
    if winner["model_type"] == "block_poly2":
        head = fit_block_head(
            full,
            target,
            wells=wells,
            static_feature_names=static_names,
            weights=tuple(winner["weights"]),
            mode=winner["mode"],
            ridge=winner["ridge"],
            dataset_hash=fit_dataset_hash,
            target_provenance_hash=target_provenance_hash,
            feature_context_sha256=feature_context_sha256,
            calibration_slope=calibration_slope,
            calibration_intercept_rub=calibration_intercept,
        )
    else:
        head = _fit_final(
            full,
            target,
            winner,
            wells=wells,
            static_feature_names=static_names,
            dataset_hash=fit_dataset_hash,
            calibration_slope=calibration_slope,
            calibration_intercept_rub=calibration_intercept,
            target_provenance_hash=target_provenance_hash,
            feature_provenance_hash=feature_implementation_hash(),
            feature_context_sha256=feature_context_sha256,
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output_dir / "npv_head.pt"
    temporary_checkpoint = args.output_dir / "npv_head.pt.tmp"
    head.save(temporary_checkpoint)
    restored = load_direct_npv_head(temporary_checkpoint)
    if restored.version != head.version:
        raise RuntimeError("serialized NPV head version differs")
    temporary_checkpoint.replace(checkpoint)
    checkpoint_sha256 = _sha256(checkpoint)
    report = {
        "format": "aios.surrogate-locked-npv-candidate.v1",
        "dataset_hash": fit_dataset_hash,
        "historical_dataset_hash": dataset_hash,
        "historical_fit_population_hash": historical_fit_population_hash,
        "fit_buckets": ["train", "validation"],
        "locked_test_read": False,
        "candidate": winner,
        "selection_oof": screen_item["oof"],
        "selection_folds": screen.get("folds"),
        "selection_group_key": screen.get("group_key"),
        "selection_protocol": screen["nested_deployable_selection"]["protocol"],
        "selection_policy_oof": screen["nested_deployable_selection"]["averaged_oof"],
        "selection_report": str(args.screen_report),
        "selection_report_sha256": _sha256(args.screen_report),
        "feature_cache": str(args.feature_cache),
        "selection_n_rows": len(identities),
        "n_rows": len(target),
        "augmentation": (
            augmentation_reports[0] if len(augmentation_reports) == 1 else None
        ),
        "augmentations": augmentation_reports,
        "checkpoint": checkpoint.name,
        "checkpoint_sha256": checkpoint_sha256,
        "model_version": head.version,
        "target_provenance_hash": head.target_provenance_hash,
        "feature_provenance_hash": head.feature_provenance_hash,
        "feature_context_sha256": head.feature_context_sha256,
        "selection_calibration": screen["deployable_calibration"],
        "fit_calibration": fit_calibration,
    }
    _write_json(args.output_dir / "lock_report.json", report)
    print(f"locked {checkpoint}; version={head.version}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
