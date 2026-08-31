from pathlib import Path

import pytest

from backend.application.optimization.opm_active_calibration import (
    OpmActiveCalibrationError,
    WaterFamilyNpvCalibration,
)
from backend.application.optimization.runtime_artifacts import resolve_runtime_artifacts
from backend.ml.surrogate.npv_head import ScenarioNpvHead


def _load() -> WaterFamilyNpvCalibration:
    root = Path(__file__).resolve().parents[4]
    runtime = resolve_runtime_artifacts()
    head = ScenarioNpvHead.load(runtime.npv_head)
    return WaterFamilyNpvCalibration.load(
        root / "config" / "opm-active-npv-calibration.json",
        economic_model_version=head.version,
    )


def test_two_stage_blind_validated_calibration_corrects_the_champion_raw_head() -> None:
    calibration = _load()
    result = calibration.predict(10_558_445_546.343525)

    assert result.trusted
    assert result.npv_rub == pytest.approx(7_755_946_517.559187)
    assert calibration.blind_holdout_absolute_relative_error < 0.004
    assert calibration.blind_extension_absolute_relative_error < 0.005
    assert calibration.loocv_mae_rub < 17_000_000.0


def test_calibration_refuses_to_extrapolate_beyond_measured_raw_range() -> None:
    calibration = _load()
    result = calibration.predict(calibration.raw_max_rub + 100_000_000.0)

    assert result.npv_rub is None
    assert result.domain_score > 0.0


def test_calibration_is_bound_to_the_economic_head_version() -> None:
    root = Path(__file__).resolve().parents[4]
    with pytest.raises(OpmActiveCalibrationError, match="different economic head"):
        WaterFamilyNpvCalibration.load(
            root / "config" / "opm-active-npv-calibration.json",
            economic_model_version="0" * 64,
        )
