"""Benchmark nonlinear scenario-NPV regressors without reading the locked test.

This is a training-only experiment.  It deliberately builds its matrix from
the historical ``train`` and ``validation`` buckets and groups equal canonical
schedules so that duplicated schedules can never straddle a CV fold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import sklearn
import torch
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import (
    ExtraTreesRegressor,
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.feature_selection import SelectKBest, f_regression
from sklearn.kernel_approximation import Nystroem
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from surrogate.metrics import ranking_metrics
from surrogate.npv_block_head import DEFAULT_BLOCKS, block_implementation_hash
from surrogate.npv_head import feature_implementation_hash, scenario_feature_vector
from surrogate.npv_target import validate_target_provenance

FEATURE_WIDTHS = {
    "global": 84,
    "temporal": 1260,
    "full": 2908,
    "economic": 4406,
}
BUCKETS = ("train", "validation")
SELECTION_BAND = 0.02
REPORT_FORMAT = "aios.surrogate-npv-model-screen.v2"
BLOCK_WEIGHT_SHORTLIST = (
    (0.0, 0.7, 0.3, 0.0),
    (0.15, 0.25, 0.55, 0.05),
    (0.03, 0.40, 0.52, 0.05),
    (0.05, 0.45, 0.30, 0.20),
    (0.05, 0.25, 0.25, 0.45),
    (0.0, 0.15, 0.20, 0.65),
    (0.05, 0.25, 0.25, 0.45),
)
BLOCK_MODE_SHORTLIST = (
    "joint",
    "joint",
    "joint",
    "joint",
    "joint",
    "joint",
    "additive",
)
BLOCK_RIDGES = (0.3, 1.0, 3.0)
BLOCK_SHORTLIST_PROVENANCE = {
    "frozen_before_blind1_labels": True,
    "source": "data/npv-v3/kernel_screen_report.json",
    "source_sha256": "f6cd7035c4f767bfe0b9d0210e8c1027ffc0a7c340d86abdc0d329d3672bfeb9",
    "source_population": "historical train+validation; legacy target; no test/blind",
    "same_schedule_population_prior_target_reuse": True,
    "nested_metrics_are_provisional_until_blind2": True,
    "legacy_audit_spec_indices": [0, 1, 2, 3],
    "domain_hypothesis_spec_indices": [4, 5, 6],
    "domain_hypothesis_frozen_before_blind1_labels": True,
    "domain_hypothesis_rationale": (
        "event OPEX is schedule-additive and may benefit from a stronger economic block"
    ),
    "weights": [list(item) for item in BLOCK_WEIGHT_SHORTLIST],
    "modes": list(BLOCK_MODE_SHORTLIST),
    "ridges": list(BLOCK_RIDGES),
}
SELECTION_RULE = {
    "spearman_equivalence_band": SELECTION_BAND,
    "tie_break_order": [
        "regret_at_5_rub",
        "rank_of_true_best",
        "negative_precision_at_5",
        "mae_rub",
        "negative_spearman",
        "candidate_id",
    ],
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tensors",
        type=Path,
        help="legacy fallback only; v4 cache v2 must work without this monolith",
    )
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument("--trees", type=int, default=256)
    parser.add_argument("--outer-folds", type=int, default=5)
    parser.add_argument("--outer-repeats", type=int, default=3)
    return parser


def _write_json(path: Path, payload: dict[str, Any]) -> None:
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


def screen_implementation_hash() -> str:
    return _sha256(Path(__file__))


def screen_runtime_versions() -> dict[str, str]:
    return {
        "numpy": str(np.__version__),
        "scikit_learn": str(sklearn.__version__),
        "torch": str(torch.__version__),
    }


def _feature_matrix(blob: dict[str, Any]) -> tuple[torch.Tensor, list[dict[str, str]]]:
    vectors: list[torch.Tensor] = []
    identities: list[dict[str, str]] = []
    for bucket in BUCKETS:
        x, well_index, _ = blob["tensors"][bucket]
        offset = 0
        counts = blob["counts"][bucket]
        for index, (count, identity) in enumerate(
            zip(counts, blob["identities"][bucket], strict=True), start=1
        ):
            stop = offset + count
            vectors.append(
                scenario_feature_vector(
                    x[offset:stop],
                    well_index[offset:stop],
                    n_wells=len(blob["wells"]),
                    feature_set="economic",
                ).to(torch.float32)
            )
            identities.append({"bucket": bucket, **identity})
            offset = stop
            if index == 1 or index % 50 == 0 or index == len(counts):
                print(f"{bucket}: features {index}/{len(counts)}", flush=True)
        if offset != len(x):
            raise RuntimeError(f"{bucket}: counts do not cover tensor")
    return torch.stack(vectors), identities


def _validate_selection_labels(labels: dict[str, Any]) -> None:
    if labels.get("format") != "aios.surrogate-npv-labels.v1":
        raise RuntimeError("unsupported labels artifact")
    if (
        labels.get("historical_test_read") is not False
        or labels.get("included_buckets") != list(BUCKETS)
        or labels.get("expected_rows") != 595
        or len(labels.get("rows", {})) != 595
    ):
        raise RuntimeError(
            "selection labels must be a response-proven train+validation-only artifact"
        )
    if any(row.get("bucket") not in BUCKETS for row in labels["rows"].values()):
        raise RuntimeError("selection labels contain a retired test row")
    validate_target_provenance(labels.get("target_provenance"))


def _unique_schedule_population(
    matrix: np.ndarray,
    target: np.ndarray,
    identities: list[dict[str, str]],
    response_hashes: list[str],
) -> tuple[np.ndarray, np.ndarray, list[dict[str, str]]]:
    """Collapse exact schedule duplicates only when labels and features agree."""

    if not (
        len(matrix) == len(target) == len(identities) == len(response_hashes)
    ):
        raise RuntimeError("selection axes differ before schedule deduplication")
    first_by_schedule: dict[str, int] = {}
    keep = []
    for index, (identity, response_hash) in enumerate(
        zip(identities, response_hashes, strict=True)
    ):
        schedule_hash = identity["canonical_schedule_hash"]
        previous = first_by_schedule.get(schedule_hash)
        if previous is None:
            first_by_schedule[schedule_hash] = index
            keep.append(index)
            continue
        if (
            response_hashes[previous] != response_hash
            or target[previous] != target[index]
            or not np.array_equal(matrix[previous], matrix[index])
        ):
            raise RuntimeError(
                f"duplicate schedule has inconsistent evidence: {schedule_hash}"
            )
    return matrix[keep], target[keep], [identities[index] for index in keep]


def _load_selection_data(
    tensors: Path | None,
    labels_path: Path,
    feature_cache: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, str]], str]:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    _validate_selection_labels(labels)
    cached = (
        torch.load(feature_cache, map_location="cpu", weights_only=False)
        if feature_cache.exists()
        else None
    )
    blob: dict[str, Any] | None = None
    if isinstance(cached, dict) and cached.get("format") == (
        "aios.npv-selection-features.v2"
    ):
        context_sha256 = cached.get("feature_context_sha256")
        if (
            cached.get("response_data_read") is not False
            or cached.get("historical_test_read") is not False
            or cached.get("feature_set") != "economic"
            or cached.get("feature_width") != FEATURE_WIDTHS["economic"]
            or cached.get("feature_provenance_hash") != feature_implementation_hash()
            or cached.get("dataset_hash") != labels.get("dataset_hash")
            or not isinstance(context_sha256, str)
            or len(context_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in context_sha256
            )
        ):
            raise RuntimeError("safe feature cache provenance differs")
        identities = cached.get("identities")
        if not isinstance(identities, list) or len(identities) != 595:
            raise RuntimeError("safe feature cache population differs")
        dataset_hash = str(cached["dataset_hash"])
    else:
        if tensors is None:
            raise RuntimeError("v4 requires a self-contained safe feature cache v2")
        blob = torch.load(tensors, map_location="cpu", weights_only=False, mmap=True)
        if blob.get("format") != "aios.surrogate-tensors.v2":
            raise RuntimeError("unsupported tensors artifact")
        if labels.get("dataset_hash") != blob.get("dataset_hash"):
            raise RuntimeError("dataset hashes differ")

        cache_key = hashlib.sha256(
            (
                f"{blob['dataset_hash']}:economic:train+validation:"
                f"{feature_implementation_hash()}"
            ).encode()
        ).hexdigest()
        if cached is not None and (
            not isinstance(cached, dict) or cached.get("cache_key") != cache_key
        ):
            raise RuntimeError("refusing to overwrite an incompatible feature cache")
        if cached is None:
            features, identities = _feature_matrix(blob)
            cached = {
                "format": "aios.npv-selection-features.v1",
                "cache_key": cache_key,
                "dataset_hash": blob["dataset_hash"],
                "features": features,
                "identities": identities,
            }
            feature_cache.parent.mkdir(parents=True, exist_ok=True)
            torch.save(cached, feature_cache)
        identities = cached["identities"]
        expected_identities = [
            {"bucket": bucket, **identity}
            for bucket in BUCKETS
            for identity in blob["identities"][bucket]
        ]
        if identities != expected_identities:
            raise RuntimeError("feature cache identities differ from tensor artifact")
        dataset_hash = str(blob["dataset_hash"])
    features = cached.get("features")
    if not isinstance(features, torch.Tensor) or features.shape != (
        len(identities),
        FEATURE_WIDTHS["economic"],
    ):
        raise RuntimeError("feature cache matrix shape differs")
    if not bool(torch.isfinite(features).all()):
        raise RuntimeError("feature cache contains non-finite values")
    targets = []
    response_hashes = []
    for identity in identities:
        if identity["bucket"] not in BUCKETS:
            raise RuntimeError("feature cache contains locked test identity")
        key = f"{identity['source_dataset']}:{identity['scenario_id']}"
        row = labels["rows"][key]
        if row["bucket"] != identity["bucket"]:
            raise RuntimeError(f"{key}: bucket mismatch")
        if row["canonical_schedule_hash"] != identity["canonical_schedule_hash"]:
            raise RuntimeError(f"{key}: schedule hash mismatch")
        value = row.get("npv_rub")
        if type(value) not in (int, float) or not math.isfinite(float(value)):
            raise RuntimeError(f"{key}: target is non-finite")
        targets.append(float(value))
        response_hash = row.get("response_hash")
        if not isinstance(response_hash, str) or len(response_hash) != 64:
            raise RuntimeError(f"{key}: response hash is invalid")
        response_hashes.append(response_hash)
    matrix, unique_target, identities = _unique_schedule_population(
        features.numpy(),
        np.asarray(targets, dtype=np.float64),
        identities,
        response_hashes,
    )
    return (
        matrix,
        unique_target,
        np.asarray([item["canonical_schedule_hash"] for item in identities]),
        identities,
        dataset_hash,
    )


def _target_scaled(estimator: RegressorMixin) -> RegressorMixin:
    return TransformedTargetRegressor(
        regressor=estimator,
        transformer=StandardScaler(),
    )


class BlockKernelRegressor(RegressorMixin, BaseEstimator):
    def __init__(
        self, *, weights: tuple[float, ...], mode: str, ridge: float
    ) -> None:
        self.weights = weights
        self.mode = mode
        self.ridge = ridge

    def _kernel(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        components = []
        component_weights = []
        for weight, (_, start, stop), width in zip(
            self.weights, DEFAULT_BLOCKS, self.active_widths_, strict=True
        ):
            if weight == 0.0:
                continue
            if width < 1:
                raise RuntimeError("weighted block has no active features")
            components.append(left[:, start:stop] @ right[:, start:stop].T / width)
            component_weights.append(weight)
        if self.mode == "joint":
            mixed = sum(
                weight * item
                for weight, item in zip(
                    component_weights, components, strict=True
                )
            )
            return np.square(1.0 + mixed)
        if self.mode == "additive":
            return sum(
                weight * np.square(1.0 + item)
                for weight, item in zip(
                    component_weights, components, strict=True
                )
            )
        raise RuntimeError(f"unknown block kernel mode: {self.mode}")

    def fit(self, matrix: np.ndarray, target: np.ndarray) -> BlockKernelRegressor:
        values = np.asarray(matrix, dtype=np.float64)
        actual = np.asarray(target, dtype=np.float64)
        self.mean_ = values.mean(axis=0)
        raw_scale = values.std(axis=0)
        self.active_widths_ = tuple(
            int(np.sum(raw_scale[start:stop] > 1.0e-10))
            for _, start, stop in DEFAULT_BLOCKS
        )
        self.scale_ = np.where(raw_scale > 1.0e-10, raw_scale, 1.0)
        self.centers_ = (values - self.mean_) / self.scale_
        gram = self._kernel(self.centers_, self.centers_)
        gram = (gram + gram.T) * 0.5
        gram.flat[:: len(gram) + 1] += self.ridge
        self.dual_ = np.linalg.solve(gram, actual)
        return self

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        values = (np.asarray(matrix, dtype=np.float64) - self.mean_) / self.scale_
        return self._kernel(values, self.centers_) @ self.dual_


class RbfKernelRegressor(RegressorMixin, BaseEstimator):
    """Exact deployable RBF KRR with the runtime's median-distance gamma."""

    def __init__(self, *, gamma_factor: float, ridge: float) -> None:
        self.gamma_factor = gamma_factor
        self.ridge = ridge

    @staticmethod
    def _distances(left: np.ndarray, right: np.ndarray) -> np.ndarray:
        result = (
            np.square(left).sum(axis=1, keepdims=True)
            + np.square(right).sum(axis=1)[None, :]
            - 2.0 * left @ right.T
        )
        return np.maximum(result, 0.0)

    def fit(self, matrix: np.ndarray, target: np.ndarray) -> RbfKernelRegressor:
        values = np.asarray(matrix, dtype=np.float64)
        actual = np.asarray(target, dtype=np.float64)
        self.mean_ = values.mean(axis=0)
        raw_scale = values.std(axis=0)
        self.scale_ = np.where(raw_scale > 1.0e-10, raw_scale, 1.0)
        self.centers_ = (values - self.mean_) / self.scale_
        distances = self._distances(self.centers_, self.centers_)
        positive = distances[distances > 1.0e-12]
        if not len(positive):
            raise RuntimeError("RBF candidate has no positive pairwise distance")
        # torch.median, used by the deployed head fitter, selects the lower
        # middle item for an even population rather than averaging the pair.
        middle = (len(positive) - 1) // 2
        median = float(np.partition(positive, middle)[middle])
        self.gamma_ = self.gamma_factor / median
        gram = np.exp(-self.gamma_ * distances)
        gram = (gram + gram.T) * 0.5
        gram.flat[:: len(gram) + 1] += self.ridge
        self.dual_ = np.linalg.solve(gram, actual)
        return self

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        values = (np.asarray(matrix, dtype=np.float64) - self.mean_) / self.scale_
        return np.exp(
            -self.gamma_ * self._distances(values, self.centers_)
        ) @ self.dual_


def _block_candidate_id(spec_index: int, ridge: float) -> str:
    return f"block-{BLOCK_MODE_SHORTLIST[spec_index]}-s{spec_index}-a{ridge:g}"


def _deployable_spec(candidate_id: str) -> dict[str, Any] | None:
    match = re.fullmatch(
        r"krr-linear-(global|temporal|full|economic)-a([0-9]+(?:\.[0-9]+)?)",
        candidate_id,
    )
    if match is not None:
        return {
            "model_type": "scenario_kernel",
            "feature_set": match.group(1),
            "kernel": "linear",
            "gamma": 1.0,
            "gamma_factor": None,
            "ridge": float(match.group(2)),
        }
    match = re.fullmatch(
        r"krr-poly2-(global|temporal|full|economic)-a([0-9]+(?:\.[0-9]+)?)",
        candidate_id,
    )
    if match is not None:
        return {
            "model_type": "scenario_poly2",
            "feature_set": match.group(1),
            "kernel": "poly2",
            "gamma": 1.0,
            "gamma_factor": None,
            "ridge": float(match.group(2)),
        }
    match = re.fullmatch(
        r"krr-rbf-(global|temporal|full|economic)-g([0-9]+(?:\.[0-9]+)?)-a([0-9]+(?:\.[0-9]+)?)",
        candidate_id,
    )
    if match is not None:
        return {
            "model_type": "scenario_kernel",
            "feature_set": match.group(1),
            "kernel": "rbf",
            "gamma": 1.0,
            "gamma_factor": float(match.group(2)),
            "ridge": float(match.group(3)),
        }
    match = re.fullmatch(
        r"block-(joint|additive)-s([0-9]+)-a([0-9]+(?:\.[0-9]+)?)",
        candidate_id,
    )
    if match is None:
        return None
    mode = match.group(1)
    index = int(match.group(2))
    ridge = float(match.group(3))
    if (
        index >= len(BLOCK_WEIGHT_SHORTLIST)
        or mode != BLOCK_MODE_SHORTLIST[index]
        or ridge not in BLOCK_RIDGES
    ):
        return None
    return {
        "model_type": "block_poly2",
        "mode": mode,
        "weights": list(BLOCK_WEIGHT_SHORTLIST[index]),
        "ridge": ridge,
        "shortlist_index": index,
    }


def _factories(*, seed: int, trees: int) -> dict[str, Callable[[], RegressorMixin]]:
    result: dict[str, Callable[[], RegressorMixin]] = {}
    for feature_set in ("global", "temporal", "full", "economic"):
        width = FEATURE_WIDTHS[feature_set]
        for alpha in (0.03, 0.1, 0.3, 1.0, 3.0):
            name = f"krr-linear-{feature_set}-a{alpha:g}"
            result[name] = lambda width=width, alpha=alpha: _target_scaled(
                make_pipeline(
                    StandardScaler(),
                    KernelRidge(
                        alpha=alpha,
                        kernel="polynomial",
                        degree=1,
                        gamma=1.0 / width,
                        coef0=0.0,
                    ),
                )
            )
        for alpha in (0.03, 0.1, 0.3, 1.0, 3.0):
            name = f"krr-poly2-{feature_set}-a{alpha:g}"
            result[name] = lambda width=width, alpha=alpha: _target_scaled(
                make_pipeline(
                    StandardScaler(),
                    KernelRidge(
                        alpha=alpha,
                        kernel="polynomial",
                        degree=2,
                        gamma=1.0 / width,
                        coef0=1.0,
                    ),
                )
            )

    # Keep the exact runtime-compatible RBF search logarithmic and deliberately
    # broad.  The earlier 2 x 2 x 3 screen could miss both the low-dimensional
    # views and moderately different smoothness/regularisation regimes.  The
    # repeated nested group-CV below measures the selection policy's optimism.
    for feature_set in ("global", "temporal", "full", "economic"):
        for gamma_factor in (0.03, 0.1, 0.3, 1.0, 3.0):
            for ridge in (0.03, 0.1, 0.3, 1.0, 3.0):
                name = (
                    f"krr-rbf-{feature_set}-g{gamma_factor:g}-a{ridge:g}"
                )
                result[name] = (
                    lambda gamma_factor=gamma_factor, ridge=ridge: _target_scaled(
                        RbfKernelRegressor(
                            gamma_factor=gamma_factor,
                            ridge=ridge,
                        )
                    )
                )

    for spec_index, (weights, mode) in enumerate(
        zip(BLOCK_WEIGHT_SHORTLIST, BLOCK_MODE_SHORTLIST, strict=True)
    ):
        for ridge in BLOCK_RIDGES:
            name = _block_candidate_id(spec_index, ridge)
            result[name] = (
                lambda weights=weights, mode=mode, ridge=ridge: _target_scaled(
                    BlockKernelRegressor(
                        weights=weights, mode=mode, ridge=ridge
                    )
                )
            )

    for feature_set in ("global", "temporal", "full"):
        width = FEATURE_WIDTHS[feature_set]
        for leaf in (2, 4, 8):
            for max_features in (0.35, 0.7, 1.0):
                name = f"extra-{feature_set}-leaf{leaf}-mf{max_features:g}"
                result[name] = (
                    lambda width=width, leaf=leaf, max_features=max_features: (
                        _target_scaled(
                            ExtraTreesRegressor(
                                n_estimators=trees,
                                min_samples_leaf=leaf,
                                max_features=max_features,
                                random_state=seed,
                                n_jobs=-1,
                            )
                        )
                    )
                )

    for leaf in (2, 4, 8):
        for max_features in (0.35, 0.7):
            name = f"forest-full-leaf{leaf}-mf{max_features:g}"
            result[name] = lambda leaf=leaf, max_features=max_features: _target_scaled(
                RandomForestRegressor(
                    n_estimators=trees,
                    min_samples_leaf=leaf,
                    max_features=max_features,
                    random_state=seed,
                    n_jobs=-1,
                )
            )

    for selected in (32, 64, 128, 256):
        for leaf in (5, 10):
            name = f"gbr-full-k{selected}-leaf{leaf}"
            result[name] = lambda selected=selected, leaf=leaf: _target_scaled(
                make_pipeline(
                    SelectKBest(f_regression, k=selected),
                    GradientBoostingRegressor(
                        n_estimators=300,
                        learning_rate=0.03,
                        max_depth=2,
                        min_samples_leaf=leaf,
                        loss="huber",
                        random_state=seed,
                    ),
                )
            )
    for selected in (32, 64, 128, 256):
        for leaf in (10, 20):
            name = f"hist-full-k{selected}-leaf{leaf}"
            result[name] = lambda selected=selected, leaf=leaf: _target_scaled(
                make_pipeline(
                    SelectKBest(f_regression, k=selected),
                    HistGradientBoostingRegressor(
                        max_iter=300,
                        learning_rate=0.05,
                        max_leaf_nodes=15,
                        min_samples_leaf=leaf,
                        l2_regularization=1.0,
                        early_stopping=False,
                        random_state=seed,
                    ),
                )
            )
    for components in (64, 128, 256, 400):
        for factor in (0.1, 1.0, 10.0):
            name = f"nystroem-full-c{components}-g{factor:g}"
            result[name] = lambda components=components, factor=factor: _target_scaled(
                make_pipeline(
                    StandardScaler(),
                    Nystroem(
                        kernel="rbf",
                        gamma=factor / FEATURE_WIDTHS["full"],
                        n_components=components,
                        random_state=seed,
                    ),
                    Ridge(alpha=0.1),
                )
            )
    return result


def _view(matrix: np.ndarray, candidate_id: str) -> np.ndarray:
    if candidate_id.startswith("block-"):
        return matrix[:, : FEATURE_WIDTHS["economic"]]
    for feature_set, width in FEATURE_WIDTHS.items():
        if f"-{feature_set}-" in candidate_id:
            return matrix[:, :width]
    return matrix[:, : FEATURE_WIDTHS["full"]]


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    actual_values = actual.tolist()
    predicted_values = predicted.tolist()
    ranking = ranking_metrics(
        actual_values,
        predicted_values,
        k_values=(1, 3, 5, 10, 20, 40),
    )
    actual_order = np.argsort(-actual, kind="stable")
    predicted_order = np.argsort(-predicted, kind="stable")
    true_best = int(actual_order[0])
    return {
        "ranking": asdict(ranking),
        "mae_rub": float(np.mean(np.abs(predicted - actual))),
        "rmse_rub": float(np.sqrt(np.mean(np.square(predicted - actual)))),
        "bias_rub": float(np.mean(predicted - actual)),
        "rank_of_true_best": int(np.flatnonzero(predicted_order == true_best)[0] + 1),
    }


def _linear_calibration(
    actual: np.ndarray, predicted: np.ndarray
) -> dict[str, float | str]:
    """Fit actual ~= intercept + slope * OOF prediction, fail-safe to identity."""

    if actual.shape != predicted.shape or actual.ndim != 1 or len(actual) < 3:
        raise ValueError("calibration requires paired one-dimensional predictions")
    identity_mae = float(np.mean(np.abs(predicted - actual)))
    bias_intercept = float(np.median(actual - predicted))
    bias_mae = float(np.mean(np.abs(predicted + bias_intercept - actual)))
    best = {
        "method": "grouped_oof_median_bias_v1",
        "slope": 1.0,
        "intercept_rub": bias_intercept,
    }
    best_mae = bias_mae
    if bias_mae >= identity_mae:
        best = {
            "method": "identity_no_mae_gain",
            "slope": 1.0,
            "intercept_rub": 0.0,
        }
        best_mae = identity_mae
    predicted_centered = predicted - predicted.mean()
    denominator = float(predicted_centered @ predicted_centered)
    if denominator <= 1.0e-20:
        if best["method"] == "identity_no_mae_gain":
            best["method"] = "identity_degenerate"
        return best
    slope = float(predicted_centered @ (actual - actual.mean()) / denominator)
    if not math.isfinite(slope) or slope <= 0.0:
        if best["method"] == "identity_no_mae_gain":
            best["method"] = "identity_nonpositive"
        return best
    intercept = float(actual.mean() - slope * predicted.mean())
    if not math.isfinite(intercept):
        raise RuntimeError("calibration intercept is non-finite")
    ols_mae = float(np.mean(np.abs(intercept + slope * predicted - actual)))
    if ols_mae < best_mae:
        return {
            "method": "grouped_oof_ols_v1",
            "slope": slope,
            "intercept_rub": intercept,
        }
    return best


def _apply_calibration(
    predicted: np.ndarray, calibration: dict[str, float | str]
) -> np.ndarray:
    return float(calibration["intercept_rub"]) + float(calibration["slope"]) * predicted


def _cv_predict(
    factory: Callable[[], RegressorMixin],
    matrix: np.ndarray,
    target: np.ndarray,
    groups: np.ndarray,
    *,
    folds: int,
    seed: int,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    splitter = GroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    predicted = np.full(len(target), np.nan, dtype=np.float64)
    fold_reports = []
    for fold, (train, held_out) in enumerate(
        splitter.split(matrix, target, groups), start=1
    ):
        if set(groups[train]) & set(groups[held_out]):
            raise RuntimeError("group leakage detected")
        estimator = factory()
        estimator.fit(matrix[train], target[train])
        predicted[held_out] = estimator.predict(matrix[held_out])
        fold_reports.append(
            {
                "fold": fold,
                "train": len(train),
                "held_out": len(held_out),
                "metrics": _metrics(target[held_out], predicted[held_out]),
            }
        )
    if not np.isfinite(predicted).all():
        raise RuntimeError("OOF prediction is incomplete")
    return predicted, fold_reports


def _winner(items: list[dict[str, Any]]) -> dict[str, Any]:
    def at_k(mapping: dict[Any, Any], k: int, default: float) -> float:
        """Read metrics both before and after JSON turns integer keys into strings."""

        return float(mapping.get(k, mapping.get(str(k), default)))

    best_rho = max(
        item["oof"]["ranking"]["spearman_rank_correlation"] for item in items
    )
    equivalent = [
        item
        for item in items
        if item["oof"]["ranking"]["spearman_rank_correlation"]
        >= best_rho - SELECTION_BAND
    ]
    return min(
        equivalent,
        key=lambda item: (
            at_k(item["oof"]["ranking"]["regret_at_k_rub"], 5, math.inf),
            item["oof"]["rank_of_true_best"],
            -at_k(item["oof"]["ranking"]["precision_at_k"], 5, 0.0),
            item["oof"]["mae_rub"],
            -item["oof"]["ranking"]["spearman_rank_correlation"],
            item["candidate_id"],
        ),
    )


def _deployable_factories(
    factories: dict[str, Callable[[], RegressorMixin]],
) -> dict[str, Callable[[], RegressorMixin]]:
    """Return candidates representable by the audited ScenarioNpvHead runtime."""

    return {
        candidate_id: factory
        for candidate_id, factory in factories.items()
        if _deployable_spec(candidate_id) is not None
    }


def _nested_selection_policy(
    factories: dict[str, Callable[[], RegressorMixin]],
    matrix: np.ndarray,
    target: np.ndarray,
    groups: np.ndarray,
    *,
    outer_folds: int,
    outer_repeats: int,
    seed: int,
    inner_folds: int | None = None,
    resume: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Evaluate model selection on outer groups never seen by inner selection."""

    if outer_folds < 3 or outer_repeats < 1:
        raise ValueError("nested selection requires >=3 folds and >=1 repeat")
    unique_groups = len(set(groups))
    if unique_groups < outer_folds:
        raise ValueError("not enough unique groups for outer grouped CV")
    selection_folds = outer_folds if inner_folds is None else inner_folds
    if selection_folds < 3:
        raise ValueError("nested inner selection requires at least three folds")
    repeated_predictions = np.full(
        (outer_repeats, len(target)), np.nan, dtype=np.float64
    )
    fold_reports: list[dict[str, Any]] = []
    winner_counts = {candidate_id: 0 for candidate_id in factories}
    completed_folds = 0
    progress_contract = {
        "format": "aios.surrogate-nested-selection-progress.v1",
        "selection_candidates": list(factories),
        "selection_rule": SELECTION_RULE,
        "outer_folds": outer_folds,
        "inner_folds": selection_folds,
        "outer_repeats": outer_repeats,
        "seed": seed,
        "n_rows": len(target),
    }
    if resume is not None:
        for field, expected in progress_contract.items():
            if resume.get(field) != expected:
                raise RuntimeError(f"nested resume contract differs: {field}")
        stored = resume.get("repeated_predictions")
        if (
            not isinstance(stored, list)
            or len(stored) != outer_repeats
            or any(not isinstance(row, list) or len(row) != len(target) for row in stored)
        ):
            raise RuntimeError("nested resume prediction axes differ")
        repeated_predictions = np.asarray(
            [
                [np.nan if value is None else float(value) for value in row]
                for row in stored
            ],
            dtype=np.float64,
        )
        fold_reports = resume.get("folds")
        if not isinstance(fold_reports, list):
            raise RuntimeError("nested resume folds are missing")
        completed_folds = len(fold_reports)
        if resume.get("completed_folds") != completed_folds or completed_folds > (
            outer_folds * outer_repeats
        ):
            raise RuntimeError("nested resume completed-fold count differs")
        expected_counts = {candidate_id: 0 for candidate_id in factories}
        for item in fold_reports:
            selected_id = item.get("selected_candidate_id")
            if selected_id not in expected_counts:
                raise RuntimeError("nested resume selected candidate is unavailable")
            expected_counts[selected_id] += 1
        if resume.get("winner_counts") != {
            key: value for key, value in expected_counts.items() if value
        }:
            raise RuntimeError("nested resume winner counts differ")
        winner_counts = expected_counts
        print(
            f"resuming nested selection at {completed_folds}/"
            f"{outer_folds * outer_repeats} folds",
            flush=True,
        )
    split_index = 0
    for repeat in range(outer_repeats):
        repeat_seed = seed + 104729 * repeat
        splitter = GroupKFold(
            n_splits=outer_folds, shuffle=True, random_state=repeat_seed
        )
        for fold, (outer_train, held_out) in enumerate(
            splitter.split(matrix, target, groups), start=1
        ):
            split_index += 1
            if split_index <= completed_folds:
                stored_report = fold_reports[split_index - 1]
                if (
                    stored_report.get("repeat") != repeat + 1
                    or stored_report.get("fold") != fold
                    or stored_report.get("seed") != repeat_seed
                    or stored_report.get("train") != len(outer_train)
                    or stored_report.get("held_out") != len(held_out)
                    or stored_report.get("held_out_indices") != held_out.tolist()
                    or not np.isfinite(repeated_predictions[repeat, held_out]).all()
                    or stored_report.get("outer_metrics")
                    != json.loads(
                        json.dumps(
                            _metrics(
                                target[held_out],
                                repeated_predictions[repeat, held_out],
                            )
                        )
                    )
                ):
                    raise RuntimeError("nested resume fold payload differs")
                continue
            train_groups = groups[outer_train]
            if len(set(train_groups)) < selection_folds:
                raise RuntimeError("not enough outer-train groups for inner CV")
            if set(train_groups) & set(groups[held_out]):
                raise RuntimeError("outer group leakage detected")
            inner_items = []
            inner_predictions: dict[str, np.ndarray] = {}
            inner_calibrations: dict[str, dict[str, float | str]] = {}
            for candidate_id, factory in factories.items():
                view = _view(matrix, candidate_id)
                inner_predicted, _ = _cv_predict(
                    factory,
                    view[outer_train],
                    target[outer_train],
                    train_groups,
                    folds=selection_folds,
                    seed=repeat_seed + fold,
                )
                inner_calibration = _linear_calibration(
                    target[outer_train], inner_predicted
                )
                inner_items.append(
                    {
                        "candidate_id": candidate_id,
                        "oof": _metrics(
                            target[outer_train],
                            _apply_calibration(
                                inner_predicted,
                                inner_calibration,
                            ),
                        ),
                    }
                )
                inner_predictions[candidate_id] = inner_predicted
                inner_calibrations[candidate_id] = inner_calibration
            selected = _winner(inner_items)
            selected_id = selected["candidate_id"]
            calibration = inner_calibrations[selected_id]
            winner_counts[selected_id] += 1
            selected_view = _view(matrix, selected_id)
            estimator = factories[selected_id]()
            estimator.fit(selected_view[outer_train], target[outer_train])
            predicted = _apply_calibration(
                estimator.predict(selected_view[held_out]), calibration
            )
            repeated_predictions[repeat, held_out] = predicted
            fold_reports.append(
                {
                    "repeat": repeat + 1,
                    "fold": fold,
                    "seed": repeat_seed,
                    "train": len(outer_train),
                    "held_out": len(held_out),
                    "held_out_indices": held_out.tolist(),
                    "selected_candidate_id": selected_id,
                    "inner_selection": selected,
                    "calibration": calibration,
                    "outer_metrics": _metrics(target[held_out], predicted),
                }
            )
            fold_metrics = fold_reports[-1]["outer_metrics"]
            print(
                f"nested repeat {repeat + 1}/{outer_repeats} "
                f"fold {fold}/{outer_folds}: selected={selected_id}; "
                f"rho={fold_metrics['ranking']['spearman_rank_correlation']:.4f}; "
                f"MAE={fold_metrics['mae_rub'] / 1e6:.2f}m",
                flush=True,
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        **progress_contract,
                        "completed_folds": len(fold_reports),
                        "winner_counts": {
                            key: value
                            for key, value in winner_counts.items()
                            if value
                        },
                        "repeated_predictions": [
                            [None if not math.isfinite(value) else float(value) for value in row]
                            for row in repeated_predictions
                        ],
                        "folds": fold_reports,
                    }
                )
    if not np.isfinite(repeated_predictions).all():
        raise RuntimeError("nested OOF prediction is incomplete")
    repeat_metrics = [
        _metrics(target, repeated_predictions[index]) for index in range(outer_repeats)
    ]
    averaged = repeated_predictions.mean(axis=0)
    return {
        "protocol": "repeated_nested_group_cv_v2",
        "selection_rule": SELECTION_RULE,
        "selection_candidates": list(factories),
        "outer_folds": outer_folds,
        "inner_folds": selection_folds,
        "outer_repeats": outer_repeats,
        "seed": seed,
        "winner_counts": {key: value for key, value in winner_counts.items() if value},
        "repeat_metrics": repeat_metrics,
        "mean_repeat_mae_rub": float(
            np.mean([item["mae_rub"] for item in repeat_metrics])
        ),
        "mean_repeat_spearman": float(
            np.mean(
                [
                    item["ranking"]["spearman_rank_correlation"]
                    for item in repeat_metrics
                ]
            )
        ),
        "averaged_oof": _metrics(target, averaged),
        "folds": json.loads(json.dumps(fold_reports)),
    }


def _resume_candidates(
    output: Path,
    *,
    contract: dict[str, Any],
    candidate_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any], float]:
    if not output.exists():
        return [], {}, 0.0
    report = json.loads(output.read_text(encoding="utf-8"))
    if report.get("status") == "complete":
        raise FileExistsError(f"refusing to overwrite complete screen: {output}")
    if report.get("format") != REPORT_FORMAT or report.get("status") != "incomplete":
        raise RuntimeError("existing model screen is not resumable")
    for field, expected in contract.items():
        if report.get(field) != expected:
            raise RuntimeError(f"screen resume contract differs: {field}")
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("screen resume candidate list is missing")
    completed_ids = [item.get("candidate_id") for item in candidates]
    if (
        completed_ids != candidate_ids[: len(completed_ids)]
        or report.get("candidate_count") != len(candidate_ids)
        or report.get("completed_candidates") != len(candidates)
        or not candidates
        or report.get("winner_so_far") != _winner(candidates)
    ):
        raise RuntimeError("screen resume candidate prefix differs")
    elapsed = report.get("seconds", 0.0)
    if type(elapsed) not in (int, float) or not math.isfinite(float(elapsed)):
        raise RuntimeError("screen resume elapsed time is invalid")
    return candidates, report, float(elapsed)


def main() -> int:
    args = _parser().parse_args()
    if args.folds < 3:
        raise ValueError("at least three folds are required")
    if args.outer_folds < 3 or args.outer_repeats < 1:
        raise ValueError("nested CV requires >=3 outer folds and >=1 repeat")
    started = time.monotonic()
    implementation_sha256 = {
        "screen": screen_implementation_hash(),
        "block_runtime": block_implementation_hash(),
        "features": feature_implementation_hash(),
    }
    input_artifacts = {
        "labels": {"path": str(args.labels), "sha256": _sha256(args.labels)},
    }
    if args.tensors is not None:
        input_artifacts["tensors"] = {
            "path": str(args.tensors),
            "sha256": _sha256(args.tensors),
        }
    matrix, target, groups, identities, dataset_hash = _load_selection_data(
        args.tensors, args.labels, args.feature_cache
    )
    input_artifacts["feature_cache"] = {
        "path": str(args.feature_cache),
        "sha256": _sha256(args.feature_cache),
    }
    target_provenance_hash = json.loads(args.labels.read_text(encoding="utf-8"))[
        "target_provenance"
    ]["target_provenance_sha256"]
    if len(target) != 593:
        raise RuntimeError(f"expected 593 unique selection schedules, got {len(target)}")
    factories = _factories(seed=args.seed, trees=args.trees)
    identity_sha256 = hashlib.sha256(
        json.dumps(identities, sort_keys=True).encode()
    ).hexdigest()
    runtime_versions = screen_runtime_versions()
    resume_contract = {
        "dataset_hash": dataset_hash,
        "target_provenance_hash": target_provenance_hash,
        "feature_provenance_hash": implementation_sha256["features"],
        "screen_implementation_sha256": implementation_sha256["screen"],
        "block_implementation_sha256": implementation_sha256["block_runtime"],
        "runtime_versions": runtime_versions,
        "input_artifacts": input_artifacts,
        "selection_buckets": list(BUCKETS),
        "locked_test_read": False,
        "group_key": "canonical_schedule_hash",
        "selection_rule": SELECTION_RULE,
        "block_shortlist_provenance": BLOCK_SHORTLIST_PROVENANCE,
        "n_rows": len(target),
        "source_rows_before_schedule_deduplication": 595,
        "duplicate_source_rows": 595 - len(target),
        "n_groups": len(set(groups)),
        "folds": args.folds,
        "outer_folds": args.outer_folds,
        "outer_repeats": args.outer_repeats,
        "seed": args.seed,
        "trees": args.trees,
        "identity_sha256": identity_sha256,
    }
    factory_items = list(factories.items())
    candidates, report, elapsed_offset = _resume_candidates(
        args.output,
        contract=resume_contract,
        candidate_ids=[item[0] for item in factory_items],
    )
    deployable_ids = set(_deployable_factories(factories))
    if candidates:
        print(
            f"resuming model screen at {len(candidates)}/{len(factories)}",
            flush=True,
        )
    for index, (candidate_id, factory) in enumerate(
        factory_items[len(candidates) :], start=len(candidates) + 1
    ):
        candidate_started = time.monotonic()
        view = _view(matrix, candidate_id)
        predicted, fold_reports = _cv_predict(
            factory,
            view,
            target,
            groups,
            folds=args.folds,
            seed=args.seed,
        )
        candidate_calibration = _linear_calibration(target, predicted)
        calibrated_predicted = _apply_calibration(predicted, candidate_calibration)
        item = {
            "candidate_id": candidate_id,
            "feature_width": view.shape[1],
            "raw_oof": _metrics(target, predicted),
            "oof_calibration": candidate_calibration,
            "oof": _metrics(target, calibrated_predicted),
            "folds": fold_reports,
            "seconds": time.monotonic() - candidate_started,
        }
        deployable_spec = _deployable_spec(candidate_id)
        if deployable_spec is not None:
            item["deployable_spec"] = deployable_spec
        candidates.append(item)
        rho = item["oof"]["ranking"]["spearman_rank_correlation"]
        print(
            f"[{index}/{len(factories)}] {candidate_id}: "
            f"rho={rho:.4f}; MAE={item['oof']['mae_rub'] / 1e6:.2f}m; "
            f"champion={item['oof']['rank_of_true_best']}; "
            f"{item['seconds']:.1f}s",
            flush=True,
        )
        report = {
            "format": REPORT_FORMAT,
            "status": "incomplete",
            **resume_contract,
            "candidate_count": len(factories),
            "completed_candidates": len(candidates),
            "winner_so_far": _winner(candidates),
            "candidates": candidates,
            "seconds": elapsed_offset + time.monotonic() - started,
        }
        _write_json(args.output, report)
    winner = _winner(candidates)
    deployable_winner = _winner(
        [item for item in candidates if item["candidate_id"] in deployable_ids]
    )
    calibration_predictions = []
    calibration_view = _view(matrix, deployable_winner["candidate_id"])
    for repeat in range(args.outer_repeats):
        repeated, _ = _cv_predict(
            factories[deployable_winner["candidate_id"]],
            calibration_view,
            target,
            groups,
            folds=args.folds,
            seed=args.seed + 104729 * repeat,
        )
        calibration_predictions.append(repeated)
    averaged_calibration_oof = np.stack(calibration_predictions).mean(axis=0)
    calibration = _linear_calibration(target, averaged_calibration_oof)
    calibrated_oof = _apply_calibration(averaged_calibration_oof, calibration)

    def checkpoint_nested(progress: dict[str, Any]) -> None:
        report["nested_progress"] = progress
        report["seconds"] = elapsed_offset + time.monotonic() - started
        _write_json(args.output, report)

    nested = _nested_selection_policy(
        _deployable_factories(factories),
        matrix,
        target,
        groups,
        outer_folds=args.outer_folds,
        outer_repeats=args.outer_repeats,
        seed=args.seed,
        inner_folds=args.folds,
        resume=report.get("nested_progress"),
        progress_callback=checkpoint_nested,
    )
    final_inputs = [("labels", args.labels), ("feature_cache", args.feature_cache)]
    if args.tensors is not None:
        final_inputs.append(("tensors", args.tensors))
    for name, path in final_inputs:
        if _sha256(path) != input_artifacts[name]["sha256"]:
            raise RuntimeError(f"{name} artifact changed during model screen")
    final_implementation_sha256 = {
        "screen": screen_implementation_hash(),
        "block_runtime": block_implementation_hash(),
        "features": feature_implementation_hash(),
    }
    if final_implementation_sha256 != implementation_sha256:
        raise RuntimeError("model-screen implementation changed during execution")
    report.pop("nested_progress", None)
    report.update(
        {
            "status": "complete",
            "winner": winner,
            "deployable_winner": deployable_winner,
            "deployable_calibration": {
                **calibration,
                "candidate_id": deployable_winner["candidate_id"],
                "oof_repeats": args.outer_repeats,
                "raw_averaged_oof": _metrics(target, averaged_calibration_oof),
                "calibrated_oof": _metrics(target, calibrated_oof),
            },
            "nested_deployable_selection": nested,
            "seconds": elapsed_offset + time.monotonic() - started,
        }
    )
    _write_json(args.output, report)
    print(
        f"winner: {winner['candidate_id']}; "
        f"deployable: {deployable_winner['candidate_id']}; "
        f"nested MAE={nested['mean_repeat_mae_rub'] / 1e6:.2f}m",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
