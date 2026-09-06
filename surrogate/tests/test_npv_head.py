from __future__ import annotations

import numpy as np
import pytest
import torch

from contracts import N_INTERVALS
from surrogate.features import SurrogateInput
from surrogate.npv_head import (
    BASE_FEATURES,
    ECONOMIC_AGGREGATIONS,
    ECONOMIC_WELL_FEATURES,
    TEMPORAL_BINS,
    WELL_TEMPORAL_FEATURES,
    ScenarioNpvHead,
    ScenarioNpvHeadError,
    _economic_event_vector,
    feature_implementation_hash,
    scenario_feature_vector,
)
from tools.surrogate_benchmark_npv_models import _factories
from tools.surrogate_train_npv_head import _fit_final


def _scenario(n_wells: int = 3) -> tuple[torch.Tensor, torch.Tensor]:
    steps = torch.arange(N_INTERVALS).repeat_interleave(n_wells)
    wells = torch.arange(n_wells).repeat(N_INTERVALS)
    x = torch.zeros(N_INTERVALS * n_wells, BASE_FEATURES)
    x[:, 0] = steps
    x[:, 1] = wells
    x[:, 11] = steps / (N_INTERVALS - 1)
    return x, wells


def test_scenario_feature_sets_have_stable_dimensions() -> None:
    x, wells = _scenario()

    global_vector = scenario_feature_vector(x, wells, n_wells=3, feature_set="global")
    temporal_vector = scenario_feature_vector(
        x, wells, n_wells=3, feature_set="temporal"
    )
    full_vector = scenario_feature_vector(x, wells, n_wells=3, feature_set="full")
    well_temporal_vector = scenario_feature_vector(
        x, wells, n_wells=3, feature_set="well_temporal"
    )
    economic_vector = scenario_feature_vector(
        x, wells, n_wells=3, feature_set="economic"
    )

    global_width = BASE_FEATURES * 4
    temporal_width = TEMPORAL_BINS * BASE_FEATURES * 2
    assert global_vector.shape == (global_width,)
    assert temporal_vector.shape == (global_width + temporal_width,)
    assert full_vector.shape == (global_width + temporal_width + 3 * 8 * 2,)
    assert well_temporal_vector.shape == (
        global_width
        + temporal_width
        + 3 * 8 * 2
        + TEMPORAL_BINS * 3 * WELL_TEMPORAL_FEATURES,
    )
    assert economic_vector.shape == (
        len(full_vector)
        + ECONOMIC_AGGREGATIONS * ECONOMIC_WELL_FEATURES
        + 3 * ECONOMIC_WELL_FEATURES,
    )
    assert torch.isfinite(full_vector).all()


def test_economic_event_vector_preserves_conversion_through_shut() -> None:
    grid = torch.zeros(N_INTERVALS, 1, BASE_FEATURES, dtype=torch.float64)
    grid[:, :, 15] = 1.0  # available
    grid[:, :, 20] = 1.0  # shut
    grid[0:2, :, 17] = 1.0  # producer
    grid[0:2, :, 19] = 1.0  # open
    grid[0:2, :, 20] = 0.0
    grid[4:6, :, 18] = 1.0  # injector after SHUT
    grid[4:6, :, 19] = 1.0
    grid[4:6, :, 20] = 0.0
    grid[7:8, :, 18] = 1.0  # same-role restart after SHUT
    grid[7:8, :, 19] = 1.0
    grid[7:8, :, 20] = 0.0

    vector = _economic_event_vector(grid)
    per_well = vector[ECONOMIC_AGGREGATIONS * ECONOMIC_WELL_FEATURES :]

    assert per_well[3].item() == 1.0  # first launch
    assert per_well[4].item() == 1.0  # injector restart
    assert per_well[5].item() == 1.0  # producer -> SHUT -> injector
    assert per_well[6].item() == 0.0  # forbidden reverse conversion absent
    assert per_well[7].item() == 3.0  # three active -> SHUT transitions


def test_scenario_feature_vector_rejects_incomplete_grid() -> None:
    x, wells = _scenario()
    wells[-1] = wells[-2]

    with pytest.raises(ScenarioNpvHeadError, match="дубли"):
        scenario_feature_vector(x, wells, n_wells=3)


def test_npv_head_round_trip_preserves_prediction_and_fingerprint(tmp_path) -> None:
    x, wells = _scenario(n_wells=2)
    vector = scenario_feature_vector(x, wells, n_wells=2, feature_set="global")
    width = len(vector)
    head = ScenarioNpvHead(
        wells=("A", "B"),
        static_feature_names=("i", "j", "depth"),
        feature_set="global",
        kernel="linear",
        gamma=1.0,
        feature_mean=torch.zeros(width, dtype=torch.float64),
        feature_scale=torch.ones(width, dtype=torch.float64),
        centers=torch.stack((vector, vector + 1.0)),
        dual=torch.tensor((0.25, -0.5), dtype=torch.float64),
        target_mean_rub=1_000.0,
        target_scale_rub=100.0,
        dataset_hash="dataset-1",
        target_provenance_hash="a" * 64,
        feature_provenance_hash=feature_implementation_hash(),
        feature_context_sha256="b" * 64,
        calibration_slope=0.75,
        calibration_intercept_rub=25.0,
    )

    path = head.save(tmp_path / "npv_head.pt")
    restored = ScenarioNpvHead.load(path)

    assert restored.version == head.version
    assert restored.calibration_slope == pytest.approx(0.75)
    assert restored.target_provenance_hash == "a" * 64
    assert restored.feature_provenance_hash == feature_implementation_hash()
    assert restored.feature_context_sha256 == "b" * 64
    assert restored.predict_vector(vector) == pytest.approx(head.predict_vector(vector))
    assert restored.predict_vectors(
        torch.stack((vector, vector))
    ).tolist() == pytest.approx(
        [head.predict_vector(vector), head.predict_vector(vector)]
    )

    wrong_static = SurrogateInput(
        canonical_schedule_hash="schedule",
        wells=("A", "B"),
        static_feature_names=("wrong", "j", "depth"),
        nodes=(),
        lambda_edges=(),
    )
    with pytest.raises(ScenarioNpvHeadError, match="статика"):
        restored.predict(wrong_static)


def test_deployable_screen_kernel_matches_runtime_head() -> None:
    generator = torch.Generator().manual_seed(91)
    matrix = torch.randn(
        30, BASE_FEATURES * 4, dtype=torch.float64, generator=generator
    )
    target = torch.randn(30, dtype=torch.float64, generator=generator) * 2.0e8
    candidate_id = "krr-poly2-global-a0.3"
    estimator = _factories(seed=91, trees=2)[candidate_id]()
    estimator.fit(matrix.numpy(), target.numpy())
    expected = estimator.predict(matrix.numpy())
    winner = {
        "candidate_id": candidate_id,
        "feature_set": "global",
        "kernel": "poly2",
        "gamma": 1.0,
        "gamma_factor": None,
        "ridge": 0.3,
    }

    head = _fit_final(
        matrix,
        target,
        winner,
        wells=("A", "B"),
        static_feature_names=("i", "j", "depth"),
        dataset_hash="dataset",
    )

    assert np.allclose(head.predict_vectors(matrix).numpy(), expected, rtol=1.0e-10)


def test_deployable_linear_screen_kernel_matches_runtime_head() -> None:
    generator = torch.Generator().manual_seed(93)
    matrix = torch.randn(
        30, BASE_FEATURES * 4, dtype=torch.float64, generator=generator
    )
    target = torch.randn(30, dtype=torch.float64, generator=generator) * 2.0e8
    candidate_id = "krr-linear-global-a3"
    estimator = _factories(seed=93, trees=2)[candidate_id]()
    estimator.fit(matrix.numpy(), target.numpy())
    expected = estimator.predict(matrix.numpy())
    winner = {
        "candidate_id": candidate_id,
        "model_type": "scenario_kernel",
        "feature_set": "global",
        "kernel": "linear",
        "gamma": 1.0,
        "gamma_factor": None,
        "ridge": 3.0,
    }

    head = _fit_final(
        matrix,
        target,
        winner,
        wells=("A", "B"),
        static_feature_names=("i", "j", "depth"),
        dataset_hash="dataset",
    )

    assert np.allclose(head.predict_vectors(matrix).numpy(), expected, rtol=1.0e-10)


def test_deployable_rbf_screen_kernel_matches_runtime_head() -> None:
    generator = torch.Generator().manual_seed(92)
    matrix = torch.randn(
        31, BASE_FEATURES * 4, dtype=torch.float64, generator=generator
    )
    target = torch.randn(31, dtype=torch.float64, generator=generator) * 2.0e8
    candidate_id = "krr-rbf-full-g1-a0.3"
    estimator = _factories(seed=92, trees=2)[candidate_id]()
    estimator.fit(matrix.numpy(), target.numpy())
    expected = estimator.predict(matrix.numpy())
    winner = {
        "candidate_id": candidate_id,
        "model_type": "scenario_kernel",
        "feature_set": "full",
        "kernel": "rbf",
        "gamma": 1.0,
        "gamma_factor": 1.0,
        "ridge": 0.3,
    }

    head = _fit_final(
        matrix,
        target,
        winner,
        wells=("A", "B"),
        static_feature_names=("i", "j", "depth"),
        dataset_hash="dataset",
    )

    assert np.allclose(head.predict_vectors(matrix).numpy(), expected, rtol=1.0e-9)
