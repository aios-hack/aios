from __future__ import annotations

import numpy as np
import pytest
import torch

from backend.ml.surrogate.npv_block_head import (
    BlockKernelNpvHead,
    BlockNpvHeadError,
    fit_block_head,
    load_direct_npv_head,
)


@pytest.mark.parametrize("mode", ["joint", "additive"])
def test_block_npv_head_round_trip(mode: str, tmp_path) -> None:
    generator = torch.Generator().manual_seed(77)
    features = torch.randn(24, 4406, dtype=torch.float64, generator=generator)
    target = (
        2.0e8 * features[:, 100] - 1.0e8 * features[:, 1400] + 0.5e8 * features[:, 3100]
    )
    head = fit_block_head(
        features,
        target,
        wells=("A", "B"),
        static_feature_names=("i", "j", "depth"),
        weights=(0.1, 0.5, 0.3, 0.1),
        mode=mode,
        ridge=0.3,
        dataset_hash="d" * 64,
        target_provenance_hash="a" * 64,
        feature_context_sha256="c" * 64,
        calibration_slope=1.2,
        calibration_intercept_rub=-5.0e6,
    )

    path = head.save(tmp_path / "block_head.pt")
    restored = BlockKernelNpvHead.load(path)
    generic = load_direct_npv_head(path)

    assert restored.version == head.version
    assert restored.ridge == pytest.approx(0.3)
    assert isinstance(generic, BlockKernelNpvHead)
    assert restored.predict_vectors(features) == pytest.approx(
        head.predict_vectors(features)
    )
    assert torch.isfinite(restored.predict_vectors(features)).all()


def test_block_npv_head_rejects_tampered_implementation_hash(tmp_path) -> None:
    features = torch.randn(8, 4406, dtype=torch.float64)
    target = torch.arange(8, dtype=torch.float64)
    path = fit_block_head(
        features,
        target,
        wells=("A",),
        static_feature_names=("i", "j", "depth"),
        weights=(0.0, 0.7, 0.3, 0.0),
        mode="joint",
        ridge=0.3,
        dataset_hash="d" * 64,
        target_provenance_hash="a" * 64,
        feature_context_sha256="c" * 64,
    ).save(tmp_path / "block_head.pt")
    payload = torch.load(path, weights_only=False)
    payload["implementation_hash"] = "0" * 64
    torch.save(payload, path)

    with pytest.raises(BlockNpvHeadError, match="implementation changed"):
        BlockKernelNpvHead.load(path)





def test_zero_weight_blocks_may_be_constant() -> None:
    features = torch.zeros(10, 4406, dtype=torch.float64)
    features[:, 84:2908] = torch.randn(10, 2824, dtype=torch.float64)
    target = torch.arange(10, dtype=torch.float64)

    head = fit_block_head(
        features,
        target,
        wells=("A",),
        static_feature_names=("i", "j", "depth"),
        weights=(0.0, 0.7, 0.3, 0.0),
        mode="joint",
        ridge=0.3,
        dataset_hash="d" * 64,
        target_provenance_hash="a" * 64,
        feature_context_sha256="c" * 64,
    )

    assert head.active_widths[0] == 0
    assert head.active_widths[3] == 0
    assert torch.isfinite(head.predict_vectors(features)).all()


@pytest.mark.parametrize("failure", ["nonfinite_features", "constant_target"])
def test_block_fit_rejects_invalid_training_population(failure: str) -> None:
    features = torch.randn(8, 4406, dtype=torch.float64)
    target = torch.arange(8, dtype=torch.float64)
    if failure == "nonfinite_features":
        features[0, 0] = torch.nan
    else:
        target.fill_(7.0)

    with pytest.raises(BlockNpvHeadError, match="finite|positive variance"):
        fit_block_head(
            features,
            target,
            wells=("A",),
            static_feature_names=("i", "j", "depth"),
            weights=(0.0, 0.7, 0.3, 0.0),
            mode="joint",
            ridge=0.3,
            dataset_hash="d" * 64,
            target_provenance_hash="a" * 64,
            feature_context_sha256="c" * 64,
        )
