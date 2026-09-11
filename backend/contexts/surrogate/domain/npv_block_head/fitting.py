from __future__ import annotations

import math

import torch
from torch import Tensor

from backend.contexts.surrogate.domain.errors import BlockNpvHeadError
from backend.contexts.surrogate.domain.npv_block_head.head import BlockKernelNpvHead
from backend.contexts.surrogate.domain.npv_block_head.kernel import (
    DEFAULT_BLOCKS,
    Mode,
    _block_kernel,
    block_implementation_hash,
)
from backend.contexts.surrogate.domain.npv_economic_features import (
    feature_implementation_hash,
)


def fit_block_head(
    features: Tensor,
    target: Tensor,
    *,
    wells: tuple[str, ...],
    static_feature_names: tuple[str, ...],
    weights: tuple[float, ...],
    mode: Mode,
    ridge: float,
    dataset_hash: str,
    target_provenance_hash: str,
    feature_context_sha256: str,
    calibration_slope: float = 1.0,
    calibration_intercept_rub: float = 0.0,
) -> BlockKernelNpvHead:
    raw = features.to(torch.float64)
    actual = target.to(torch.float64)
    if raw.ndim != 2 or raw.shape[1] != DEFAULT_BLOCKS[-1][2]:
        raise BlockNpvHeadError("block fit expects economic feature vectors")
    if actual.shape != (len(raw),) or len(raw) < 3:
        raise BlockNpvHeadError("block fit target axis differs")
    if not bool(torch.isfinite(raw).all()) or not bool(torch.isfinite(actual).all()):
        raise BlockNpvHeadError("block fit inputs must be finite")
    if ridge <= 0.0 or not math.isfinite(ridge):
        raise BlockNpvHeadError("block ridge must be positive")
    if len(weights) != len(DEFAULT_BLOCKS) or any(
        item < 0.0 or not math.isfinite(item) for item in weights
    ) or not math.isclose(sum(weights), 1.0, rel_tol=0.0, abs_tol=1.0e-9):
        raise BlockNpvHeadError("block fit weights must be finite and sum to one")
    mean = raw.mean(dim=0)
    raw_scale = raw.std(dim=0, unbiased=False)
    active_widths = tuple(
        int((raw_scale[start:stop] > 1.0e-10).sum())
        for _, start, stop in DEFAULT_BLOCKS
    )
    if any(
        weight > 0.0 and width < 1
        for weight, width in zip(weights, active_widths, strict=True)
    ):
        raise BlockNpvHeadError("weighted block has no active training features")
    scale = torch.where(raw_scale > 1.0e-10, raw_scale, torch.ones_like(raw_scale))
    centers = (raw - mean) / scale
    target_mean = float(actual.mean())
    target_scale = float(actual.std(unbiased=False))
    if target_scale <= 0.0 or not math.isfinite(target_scale):
        raise BlockNpvHeadError("block fit target must have positive variance")
    normalized = (actual - target_mean) / target_scale
    gram = _block_kernel(
        centers,
        centers,
        blocks=DEFAULT_BLOCKS,
        active_widths=active_widths,
        weights=weights,
        mode=mode,
    )
    gram = (gram + gram.T) * 0.5
    gram.diagonal().add_(ridge)
    dual = torch.linalg.solve(gram, normalized)
    return BlockKernelNpvHead(
        wells=wells,
        static_feature_names=static_feature_names,
        blocks=DEFAULT_BLOCKS,
        active_widths=active_widths,
        block_weights=weights,
        mode=mode,
        ridge=ridge,
        feature_mean=mean,
        feature_scale=scale,
        centers=centers,
        dual=dual,
        target_mean_rub=target_mean,
        target_scale_rub=target_scale,
        dataset_hash=dataset_hash,
        target_provenance_hash=target_provenance_hash,
        feature_provenance_hash=feature_implementation_hash(),
        feature_context_sha256=feature_context_sha256,
        implementation_hash=block_implementation_hash(),
        calibration_slope=calibration_slope,
        calibration_intercept_rub=calibration_intercept_rub,
    )


__all__ = [
    "fit_block_head",
]
