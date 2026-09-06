"""Screen deployable NPV heads on disclosed train-only schedules with grouped OOF."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from contracts import canonical_bytes
from surrogate.npv_head import feature_implementation_hash

if __package__:
    from tools.surrogate_benchmark_npv_models import (
        SELECTION_RULE,
        _apply_calibration,
        _cv_predict,
        _deployable_spec,
        _factories,
        _linear_calibration,
        _metrics,
        _unique_schedule_population,
        _validate_selection_labels,
        _view,
        _winner,
    )
    from tools.surrogate_fit_locked_npv_candidate import _load_augmentation
else:
    from surrogate_benchmark_npv_models import (
        SELECTION_RULE,
        _apply_calibration,
        _cv_predict,
        _deployable_spec,
        _factories,
        _linear_calibration,
        _metrics,
        _unique_schedule_population,
        _validate_selection_labels,
        _view,
        _winner,
    )
    from surrogate_fit_locked_npv_candidate import _load_augmentation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--screen-report", type=Path, required=True)
    parser.add_argument(
        "--augmentation-features", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--augmentation-labels", type=Path, action="append", default=[]
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--include-nondeployable", action="store_true")
    parser.add_argument("--nondeployable-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_population(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    _validate_selection_labels(labels)
    cached = torch.load(args.feature_cache, map_location="cpu", weights_only=False)
    screen = json.loads(args.screen_report.read_text(encoding="utf-8"))
    if (
        cached.get("format") != "aios.npv-selection-features.v2"
        or cached.get("response_data_read") is not False
        or cached.get("historical_test_read") is not False
        or cached.get("feature_set") != "economic"
        or cached.get("feature_provenance_hash") != feature_implementation_hash()
        or screen.get("locked_test_read") is not False
        or screen.get("input_artifacts", {}).get("labels", {}).get("sha256")
        != _sha256(args.labels)
        or screen.get("input_artifacts", {}).get("feature_cache", {}).get("sha256")
        != _sha256(args.feature_cache)
    ):
        raise RuntimeError("historical screen population is not the frozen safe cache")
    identities = cached.get("identities")
    matrix = cached.get("features")
    if not isinstance(identities, list) or len(identities) != 595:
        raise RuntimeError("historical identity population differs")
    if not isinstance(matrix, torch.Tensor) or matrix.shape != (595, 4406):
        raise RuntimeError("historical feature matrix differs")
    target_values = []
    response_hashes = []
    for identity in identities:
        key = f"{identity['source_dataset']}:{identity['scenario_id']}"
        row = labels["rows"].get(key)
        if not isinstance(row, dict) or row.get("canonical_schedule_hash") != identity.get(
            "canonical_schedule_hash"
        ):
            raise RuntimeError(f"{key}: historical label identity differs")
        target_values.append(float(row["npv_rub"]))
        response_hashes.append(row["response_hash"])
    unique_x, unique_y, unique_identities = _unique_schedule_population(
        matrix.to(torch.float64).numpy(),
        np.asarray(target_values, dtype=np.float64),
        identities,
        response_hashes,
    )
    if len(unique_identities) != 593:
        raise RuntimeError("historical unique schedule population differs")
    target_provenance_hash = labels["target_provenance"][
        "target_provenance_sha256"
    ]
    feature_context_sha256 = cached.get("feature_context_sha256")
    known_hashes = {
        identity["canonical_schedule_hash"] for identity in unique_identities
    }
    augmentation_records = []
    augmentation_hashes = []
    all_x = [torch.from_numpy(unique_x).to(torch.float64)]
    all_y = [torch.from_numpy(unique_y).to(torch.float64)]
    all_identities = list(unique_identities)
    for features_path, labels_path in zip(
        args.augmentation_features, args.augmentation_labels, strict=True
    ):
        added_x, added_y, added_identities, population_hash, excluded = (
            _load_augmentation(
                features_path,
                labels_path,
                target_provenance_hash=target_provenance_hash,
                feature_context_sha256=feature_context_sha256,
                feature_width=4406,
                historical_schedule_hashes=known_hashes,
            )
        )
        known_hashes.update(
            identity["canonical_schedule_hash"] for identity in added_identities
        )
        all_x.append(added_x)
        all_y.append(added_y)
        all_identities.extend(added_identities)
        augmentation_hashes.append(population_hash)
        augmentation_records.append(
            {
                "features": str(features_path),
                "features_sha256": _sha256(features_path),
                "labels": str(labels_path),
                "labels_sha256": _sha256(labels_path),
                "population_hash": population_hash,
                "n_rows": len(added_identities),
                "excluded_schedule_overlaps": excluded,
            }
        )
    population_hash = hashlib.sha256(
        canonical_bytes(
            {
                "format": "aios.npv-disclosed-screen-population.v1",
                "historical_labels_sha256": _sha256(args.labels),
                "historical_features_sha256": _sha256(args.feature_cache),
                "augmentation_hashes": augmentation_hashes,
                "target_provenance_hash": target_provenance_hash,
                "feature_context_sha256": feature_context_sha256,
                "canonical_schedule_hashes": sorted(known_hashes),
            }
        )
    ).hexdigest()
    full = torch.cat(all_x).numpy()
    target = torch.cat(all_y).numpy()
    groups = np.asarray(
        [identity["canonical_schedule_hash"] for identity in all_identities]
    )
    if len(full) != len(target) or len(target) != len(groups):
        raise RuntimeError("disclosed screen population is misaligned")
    return full, target, groups, {
        "population_hash": population_hash,
        "n_rows": len(target),
        "historical_test_read": False,
        "target_provenance_hash": target_provenance_hash,
        "feature_provenance_hash": feature_implementation_hash(),
        "feature_context_sha256": feature_context_sha256,
        "augmentations": augmentation_records,
    }


def main() -> int:
    args = _parser().parse_args()
    if len(args.augmentation_features) != len(args.augmentation_labels):
        raise ValueError("augmentation feature/label counts differ")
    if args.repeats < 1:
        raise ValueError("repeats must be positive")
    matrix, target, groups, population = _load_population(args)
    screen = json.loads(args.screen_report.read_text(encoding="utf-8"))
    seed = int(screen["seed"])
    folds = int(screen["folds"])
    trees = int(screen["trees"])
    factories = _factories(seed=seed, trees=trees)
    if args.include_nondeployable and args.nondeployable_only:
        raise ValueError("candidate population flags are mutually exclusive")
    candidate_ids = [
        candidate_id
        for candidate_id in factories
        if (
            (args.nondeployable_only and _deployable_spec(candidate_id) is None)
            or (
                not args.nondeployable_only
                and (args.include_nondeployable or _deployable_spec(candidate_id) is not None)
            )
        )
    ]
    contract = {
        "format": "aios.surrogate-disclosed-npv-screen.v1",
        **population,
        "base_screen": str(args.screen_report),
        "base_screen_sha256": _sha256(args.screen_report),
        "folds": folds,
        "repeats": args.repeats,
        "seed": seed,
        "trees": trees,
        "selection_rule": SELECTION_RULE,
        "include_nondeployable": args.include_nondeployable,
        "nondeployable_only": args.nondeployable_only,
        "candidate_ids": candidate_ids,
    }
    report = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.output.exists()
        else {**contract, "status": "incomplete", "candidates": []}
    )
    for key, value in contract.items():
        if report.get(key) != value:
            raise RuntimeError(f"cannot resume: disclosed screen {key} differs")
    completed = report.get("candidates")
    if not isinstance(completed, list) or [
        item.get("candidate_id") for item in completed
    ] != candidate_ids[: len(completed)]:
        raise RuntimeError("cannot resume: candidate prefix differs")
    for candidate_id in candidate_ids[len(completed) :]:
        started = time.monotonic()
        repeated = []
        fold_reports = []
        view = _view(matrix, candidate_id)
        for repeat in range(args.repeats):
            prediction, folds_payload = _cv_predict(
                factories[candidate_id],
                view,
                target,
                groups,
                folds=folds,
                seed=seed + 104729 * repeat,
            )
            repeated.append(prediction)
            fold_reports.append(folds_payload)
        averaged = np.stack(repeated).mean(axis=0)
        calibration = _linear_calibration(target, averaged)
        calibrated = _apply_calibration(averaged, calibration)
        completed.append(
            {
                "candidate_id": candidate_id,
                "deployable_spec": _deployable_spec(candidate_id),
                "feature_width": view.shape[1],
                "raw_oof": _metrics(target, averaged),
                "oof_calibration": calibration,
                "oof": _metrics(target, calibrated),
                "repeat_folds": fold_reports,
                "seconds": time.monotonic() - started,
            }
        )
        report.update(
            {
                "status": "incomplete",
                "completed_candidates": len(completed),
                "candidate_count": len(candidate_ids),
                "candidates": completed,
            }
        )
        _write(args.output, report)
        print(
            f"disclosed screen {len(completed)}/{len(candidate_ids)} "
            f"{candidate_id}",
            flush=True,
        )
    report.update(
        {
            "status": "complete",
            "completed_candidates": len(completed),
            "candidate_count": len(candidate_ids),
            "winner": _winner(completed),
        }
    )
    _write(args.output, report)
    print(f"disclosed winner: {report['winner']['candidate_id']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
