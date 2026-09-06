"""Fit a train-only per-well OOD domain and calibrate coverage on validation."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch

from surrogate.ood import NUMERIC_FEATURES
from surrogate.per_well_ood import PerWellInputDomain


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation-coverage", type=float, default=0.95)
    return parser


def _ranges(
    values: torch.Tensor, well_index: torch.Tensor, *, n_wells: int
) -> tuple[torch.Tensor, torch.Tensor]:
    width = len(NUMERIC_FEATURES)
    lows = torch.full((n_wells, width), float("inf"))
    highs = torch.full((n_wells, width), float("-inf"))
    chunk_size = 500_000
    for start in range(0, len(values), chunk_size):
        stop = start + chunk_size
        chunk = values[start:stop, :width]
        indices = well_index[start:stop, None].expand(-1, width)
        lows.scatter_reduce_(0, indices, chunk, reduce="amin", include_self=True)
        highs.scatter_reduce_(0, indices, chunk, reduce="amax", include_self=True)
    if not bool(torch.isfinite(lows).all() and torch.isfinite(highs).all()):
        raise RuntimeError("per-well fit did not cover every axis")
    return lows, highs


def _scenario_scores(
    values: torch.Tensor,
    well_index: torch.Tensor,
    counts: list[int],
    lows: torch.Tensor,
    highs: torch.Tensor,
) -> torch.Tensor:
    width = (highs - lows).clamp_min(1.0e-7)
    tolerance = 1.0e-6 * torch.maximum(
        torch.ones_like(width), torch.maximum(lows.abs(), highs.abs())
    )
    scores = []
    offset = 0
    for count in counts:
        stop = offset + count
        candidate = values[offset:stop, : len(NUMERIC_FEATURES)]
        indices = well_index[offset:stop]
        low = lows[indices]
        high = highs[indices]
        tol = tolerance[indices]
        scale = width[indices]
        exceedance = torch.maximum(
            (low - candidate - tol).clamp_min(0.0),
            (candidate - high - tol).clamp_min(0.0),
        ) / scale
        scores.append(exceedance.max())
        offset = stop
    if offset != len(values):
        raise RuntimeError("scenario counts do not cover tensor rows")
    return torch.stack(scores)


def main() -> int:
    args = _parser().parse_args()
    if not 0.5 <= args.validation_coverage < 1.0:
        raise ValueError("validation coverage must lie in [0.5, 1.0)")
    blob = torch.load(args.tensors, map_location="cpu", weights_only=False, mmap=True)
    if blob.get("format") != "aios.surrogate-tensors.v2":
        raise RuntimeError("unsupported tensor artifact")
    train, train_wells, _ = blob["tensors"]["train"]
    validation, validation_wells, _ = blob["tensors"]["validation"]
    lows, highs = _ranges(train, train_wells, n_wells=len(blob["wells"]))
    validation_scores = _scenario_scores(
        validation,
        validation_wells,
        blob["counts"]["validation"],
        lows,
        highs,
    )
    threshold = float(torch.quantile(validation_scores, args.validation_coverage))
    inside = int((validation_scores <= threshold).sum())
    domain = PerWellInputDomain(
        dataset_hash=str(blob["dataset_hash"]),
        wells=tuple(blob["wells"]),
        feature_names=NUMERIC_FEATURES,
        lows_log1p=tuple(tuple(float(value) for value in row) for row in lows),
        highs_log1p=tuple(tuple(float(value) for value in row) for row in highs),
        threshold=threshold,
        n_fit_scenarios=len(blob["counts"]["train"]),
        threshold_quantile=args.validation_coverage,
        validation_scenario_count=len(validation_scores),
        validation_inside_count=inside,
    )
    domain.save(args.output)
    print(
        f"per-well OOD threshold={threshold:.6g}; "
        f"validation inside={inside}/{len(validation_scores)}; version={domain.version}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
