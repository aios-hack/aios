from __future__ import annotations

import json

import pytest

from surrogate.npv_calibration import (
    FORMAT,
    NpvCalibration,
    NpvCalibrationError,
    calibration_metrics,
    fit_npv_calibration,
)


def test_fit_removes_affine_bias_without_changing_order() -> None:
    actual = [10.0, 20.0, 30.0, 40.0]
    predicted = [102.0, 104.0, 106.0, 108.0]

    calibration = fit_npv_calibration(actual, predicted, model_version="model-1")
    fixed = [calibration.apply(value) for value in predicted]

    assert fixed == pytest.approx(actual)
    assert calibration.slope > 0.0
    assert sorted(range(4), key=predicted.__getitem__) == sorted(
        range(4), key=fixed.__getitem__
    )


def test_calibration_round_trip_checks_model_version(tmp_path) -> None:
    path = tmp_path / "npv_calibration.json"
    expected = NpvCalibration(1.5, 0.75, "model-1")
    expected.save(path)

    assert NpvCalibration.load(path, model_version="model-1") == expected
    assert json.loads(path.read_text())["format"] == FORMAT
    with pytest.raises(NpvCalibrationError, match="другой модели"):
        NpvCalibration.load(path, model_version="model-2")


def test_non_monotone_calibration_is_rejected() -> None:
    with pytest.raises(NpvCalibrationError, match="положительным"):
        NpvCalibration(0.0, -1.0, "model-1")


def test_metrics_measure_improvement_from_fixed_calibration() -> None:
    calibration = fit_npv_calibration(
        [10.0, 20.0, 30.0], [101.0, 102.0, 103.0], model_version="model-1"
    )
    metrics = calibration_metrics(
        [15.0, 25.0], [101.5, 102.5], calibration
    )

    assert metrics["calibrated_mae_rub"] == pytest.approx(0.0)
    assert metrics["raw_mae_rub"] > metrics["calibrated_mae_rub"]
