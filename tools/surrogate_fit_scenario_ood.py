"""Fit train-only PCA/kNN scenario density and calibrate on validation."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from surrogate.scenario_ood import ScenarioDensityDomain


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--components", type=int, default=64)
    parser.add_argument("--neighbors", type=int, default=3)
    parser.add_argument("--validation-coverage", type=float, default=0.95)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite scenario OOD: {args.output}")
    if args.components < 2 or args.neighbors < 1:
        raise ValueError("scenario OOD dimensions and neighbors must be positive")
    if not 0.5 <= args.validation_coverage < 1.0:
        raise ValueError("validation coverage must lie in [0.5, 1.0)")
    cache = torch.load(args.feature_cache, map_location="cpu", weights_only=False)
    if cache.get("format") != "aios.npv-selection-features.v1":
        raise RuntimeError("unsupported NPV selection feature cache")
    identities = cache.get("identities")
    if not isinstance(identities, list) or len(identities) != 595:
        raise RuntimeError("scenario OOD requires 595 train+validation identities")
    buckets = [item.get("bucket") for item in identities]
    if buckets.count("train") != 490 or buckets.count("validation") != 105:
        raise RuntimeError("scenario OOD cache has unsafe split membership")
    matrix = cache["features"][:, :2908].numpy().astype(np.float64)
    train = matrix[np.asarray([bucket == "train" for bucket in buckets])]
    validation = matrix[np.asarray([bucket == "validation" for bucket in buckets])]
    scaler = StandardScaler().fit(train)
    active = np.flatnonzero(scaler.scale_ > 1.0e-9)
    train_scaled = scaler.transform(train)[:, active]
    validation_scaled = scaler.transform(validation)[:, active]
    if args.components >= min(train_scaled.shape):
        raise ValueError("PCA components must be below train matrix rank bound")
    pca = PCA(
        n_components=args.components,
        whiten=True,
        svd_solver="full",
    ).fit(train_scaled)
    train_embeddings = pca.transform(train_scaled)
    validation_embeddings = pca.transform(validation_scaled)
    neighbors = NearestNeighbors(n_neighbors=args.neighbors).fit(train_embeddings)
    validation_scores = neighbors.kneighbors(validation_embeddings)[0][:, -1]
    threshold = float(np.quantile(validation_scores, args.validation_coverage))
    inside = int(np.sum(validation_scores <= threshold))
    domain = ScenarioDensityDomain(
        dataset_hash=str(cache["dataset_hash"]),
        feature_width=2908,
        active_indices=torch.as_tensor(active, dtype=torch.int64),
        scaler_mean=torch.as_tensor(scaler.mean_[active], dtype=torch.float64),
        scaler_scale=torch.as_tensor(scaler.scale_[active], dtype=torch.float64),
        pca_mean=torch.as_tensor(pca.mean_, dtype=torch.float64),
        pca_components=torch.as_tensor(pca.components_, dtype=torch.float64),
        pca_explained_variance=torch.as_tensor(
            pca.explained_variance_, dtype=torch.float64
        ),
        train_embeddings=torch.as_tensor(train_embeddings, dtype=torch.float64),
        neighbors=args.neighbors,
        threshold=threshold,
        threshold_quantile=args.validation_coverage,
        validation_scenario_count=len(validation),
        validation_inside_count=inside,
    )
    stored_scores = domain.scores(torch.as_tensor(validation, dtype=torch.float64))
    if not np.allclose(stored_scores.numpy(), validation_scores, atol=1.0e-9):
        raise RuntimeError("serialized scenario OOD differs from sklearn fit")
    domain.save(args.output)
    print(
        f"scenario OOD components={domain.n_components}; k={domain.neighbors}; "
        f"threshold={domain.threshold:.6g}; validation inside="
        f"{inside}/{len(validation)}; version={domain.version}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
