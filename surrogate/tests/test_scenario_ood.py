from __future__ import annotations

import pytest
import torch

from surrogate.scenario_ood import ScenarioDensityDomain, ScenarioDensityError


def _domain() -> ScenarioDensityDomain:
    return ScenarioDensityDomain(
        dataset_hash="d" * 64,
        feature_width=3,
        active_indices=torch.tensor([0, 2], dtype=torch.int64),
        scaler_mean=torch.tensor([1.0, 2.0], dtype=torch.float64),
        scaler_scale=torch.tensor([2.0, 4.0], dtype=torch.float64),
        pca_mean=torch.zeros(2, dtype=torch.float64),
        pca_components=torch.eye(2, dtype=torch.float64),
        pca_explained_variance=torch.ones(2, dtype=torch.float64),
        train_embeddings=torch.tensor(
            [[0.0, 0.0], [1.0, 0.0], [0.0, 2.0]], dtype=torch.float64
        ),
        neighbors=2,
        threshold=1.5,
        threshold_quantile=0.95,
        validation_scenario_count=20,
        validation_inside_count=19,
    )


def test_scenario_density_scores_kth_neighbor_and_round_trips(tmp_path) -> None:
    domain = _domain()
    vector = torch.tensor([1.0, 99.0, 2.0])

    assert domain.score(vector) == pytest.approx(1.0)
    assert domain.is_inside(vector)
    path = domain.save(tmp_path / "domain.pt")
    restored = ScenarioDensityDomain.load(path)
    assert restored.version == domain.version
    assert restored.score(vector) == pytest.approx(1.0)


def test_scenario_density_rejects_tampered_fingerprint(tmp_path) -> None:
    domain = _domain()
    path = domain.save(tmp_path / "domain.pt")
    payload = torch.load(path, weights_only=False)
    payload["threshold"] = 0.5
    torch.save(payload, path)

    with pytest.raises(ScenarioDensityError, match="fingerprint"):
        ScenarioDensityDomain.load(path)
