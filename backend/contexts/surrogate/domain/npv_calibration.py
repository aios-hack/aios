"""Versioned affine calibration for surrogate-predicted NPV.

The trajectory surrogate is trained partly with a scale-invariant ranking
objective.  Its scenario ordering can therefore be useful while the absolute
NPV level remains shifted or compressed.  This artifact records the monotone
``intercept + slope * raw_npv`` correction fitted strictly on validation
scenarios.  It is deliberately separate from the physical checkpoint: the
calibration changes only the economic score, never well trajectories.
"""

from __future__ import annotations

from backend.contexts.surrogate.domain.errors import (
    NpvCalibrationError,
)

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Sequence
from backend.shared.json_io import read_json


FORMAT = "aios.surrogate-npv-calibration.v1"


@dataclass(frozen=True, slots=True)
class NpvCalibration:
    intercept_rub: float
    slope: float
    model_version: str
    fitted_on: str = "validation"
    format: str = FORMAT

    def __post_init__(self) -> None:
        if self.format != FORMAT:
            raise NpvCalibrationError(
                f"формат калибровки {self.format!r}, ожидался {FORMAT!r}"
            )
        if not math.isfinite(self.intercept_rub) or not math.isfinite(self.slope):
            raise NpvCalibrationError("коэффициенты калибровки должны быть конечными")
        if self.slope <= 0.0:
            raise NpvCalibrationError(
                "наклон калибровки должен быть положительным: отрицательный "
                "наклон переворачивает ранжирование ЧДД"
            )
        if not self.model_version:
            raise NpvCalibrationError("калибровка не содержит model_version")
        if self.fitted_on != "validation":
            raise NpvCalibrationError(
                "production-калибровка обязана подбираться на validation split"
            )

    def apply(self, raw_npv_rub: float) -> float:
        value = float(raw_npv_rub)
        if not math.isfinite(value):
            raise NpvCalibrationError("калибруемый ЧДД должен быть конечным")
        return self.intercept_rub + self.slope * value

    def save(self, path: Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    @classmethod
    def load(cls, path: Path, *, model_version: str | None = None) -> "NpvCalibration":
        payload = read_json(Path(path))
        calibration = cls(**payload)
        if model_version is not None and calibration.model_version != model_version:
            raise NpvCalibrationError(
                "калибровка относится к другой модели: "
                f"{calibration.model_version} != {model_version}"
            )
        return calibration


def fit_npv_calibration(
    actual_npv_rub: Sequence[float],
    predicted_npv_rub: Sequence[float],
    *,
    model_version: str,
) -> NpvCalibration:
    """Fit least-squares affine calibration without touching test data."""

    if len(actual_npv_rub) != len(predicted_npv_rub) or len(actual_npv_rub) < 2:
        raise NpvCalibrationError("калибровка требует хотя бы две пары ЧДД")
    actual = tuple(float(value) for value in actual_npv_rub)
    predicted = tuple(float(value) for value in predicted_npv_rub)
    if not all(math.isfinite(value) for value in actual + predicted):
        raise NpvCalibrationError("калибровка получила нечисловой ЧДД")
    predicted_mean = mean(predicted)
    actual_mean = mean(actual)
    variance = math.fsum((value - predicted_mean) ** 2 for value in predicted)
    if variance <= 0.0:
        raise NpvCalibrationError("предсказания вырождены: разброс ЧДД нулевой")
    slope = math.fsum(
        (prediction - predicted_mean) * (fact - actual_mean)
        for prediction, fact in zip(predicted, actual)
    ) / variance
    return NpvCalibration(
        intercept_rub=actual_mean - slope * predicted_mean,
        slope=slope,
        model_version=model_version,
    )


def calibration_metrics(
    actual_npv_rub: Sequence[float],
    predicted_npv_rub: Sequence[float],
    calibration: NpvCalibration,
) -> dict[str, float]:
    """Absolute-score diagnostics before and after a fixed calibration."""

    if len(actual_npv_rub) != len(predicted_npv_rub) or not actual_npv_rub:
        raise NpvCalibrationError("метрики калибровки требуют парные непустые ЧДД")
    actual = tuple(float(value) for value in actual_npv_rub)
    raw = tuple(float(value) for value in predicted_npv_rub)
    calibrated = tuple(calibration.apply(value) for value in raw)

    def mae(values: Sequence[float]) -> float:
        return mean(abs(prediction - fact) for prediction, fact in zip(values, actual))

    def bias(values: Sequence[float]) -> float:
        return mean(prediction - fact for prediction, fact in zip(values, actual))

    return {
        "raw_mae_rub": mae(raw),
        "calibrated_mae_rub": mae(calibrated),
        "raw_bias_rub": bias(raw),
        "calibrated_bias_rub": bias(calibrated),
    }
