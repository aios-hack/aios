from pathlib import Path

import pytest
import torch

from backend.ml.surrogate.npv_head import ScenarioNpvHead


def test_loads_installed_production_npv_head() -> None:
    root = Path(__file__).resolve().parents[4]
    path = root / "data" / "model-production" / "physical" / "npv_head.pt"
    if not path.is_file():
        return
    head = ScenarioNpvHead.load(path)
    assert head.feature_set == "full"
    assert head.kernel == "poly2"
    assert len(head.version) == 64
    assert head.domain_radius_rms == pytest.approx(1.3122436654351628)


def test_joint_domain_gate_rejects_unseen_feature_combinations() -> None:
    head = ScenarioNpvHead(
        wells=("1",),
        static_feature_names=("x", "y", "z"),
        feature_set="global",
        kernel="linear",
        gamma=1.0,
        feature_mean=torch.zeros(2, dtype=torch.float64),
        feature_scale=torch.ones(2, dtype=torch.float64),
        centers=torch.tensor(
            [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=torch.float64
        ),
        dual=torch.zeros(3, dtype=torch.float64),
        target_mean_rub=1.0,
        target_scale_rub=1.0,
        dataset_hash="dataset",
    )

    scores = head.domain_score_vectors(
        torch.tensor([[0.1, 0.1], [3.0, 3.0]], dtype=torch.float64)
    )

    assert scores[0] == pytest.approx(0.0)
    assert scores[1] > 0.0
