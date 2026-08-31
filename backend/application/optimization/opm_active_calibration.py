"""Local active-learning correction backed by hash-pinned OPM observations.

This is deliberately not a universal replacement for the economic head.  It
is valid only inside ``water_baseline_run``: baseline production controls with
injection projected from measured produced water.  Outside the measured raw
NPV interval it returns no corrected number and a positive domain score.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

FORMAT = "aios.water-family-npv-calibration.v1"


class OpmActiveCalibrationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CalibratedNpv:
    npv_rub: float | None
    domain_score: float

    @property
    def trusted(self) -> bool:
        return self.npv_rub is not None and self.domain_score == 0.0


@dataclass(frozen=True, slots=True)
class WaterFamilyNpvCalibration:
    slope: float
    intercept_rub: float
    raw_min_rub: float
    raw_max_rub: float
    economic_model_version: str
    version: str
    blind_holdout_absolute_relative_error: float
    blind_extension_absolute_relative_error: float
    loocv_mae_rub: float

    def __post_init__(self) -> None:
        values = (
            self.slope,
            self.intercept_rub,
            self.raw_min_rub,
            self.raw_max_rub,
            self.blind_holdout_absolute_relative_error,
            self.blind_extension_absolute_relative_error,
            self.loocv_mae_rub,
        )
        if not all(math.isfinite(value) for value in values):
            raise OpmActiveCalibrationError("calibration contains non-finite values")
        if self.slope <= 0.0 or self.raw_max_rub <= self.raw_min_rub:
            raise OpmActiveCalibrationError("calibration slope/range is invalid")
        if len(self.economic_model_version) != 64 or len(self.version) != 64:
            raise OpmActiveCalibrationError("calibration hashes must be sha256")

    def predict(self, raw_npv_rub: float) -> CalibratedNpv:
        if not math.isfinite(raw_npv_rub):
            raise OpmActiveCalibrationError("raw NPV must be finite")
        span = self.raw_max_rub - self.raw_min_rub
        if raw_npv_rub < self.raw_min_rub:
            return CalibratedNpv(None, (self.raw_min_rub - raw_npv_rub) / span)
        if raw_npv_rub > self.raw_max_rub:
            return CalibratedNpv(None, (raw_npv_rub - self.raw_max_rub) / span)
        return CalibratedNpv(
            self.intercept_rub + self.slope * raw_npv_rub,
            0.0,
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        economic_model_version: str,
    ) -> "WaterFamilyNpvCalibration":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format") != FORMAT:
            raise OpmActiveCalibrationError("unsupported active-calibration artifact")
        version = str(payload.get("version") or "")
        fingerprint_payload = dict(payload)
        fingerprint_payload.pop("version", None)
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if fingerprint != version:
            raise OpmActiveCalibrationError("active-calibration fingerprint differs")
        if payload.get("economic_model_version") != economic_model_version:
            raise OpmActiveCalibrationError(
                "active calibration belongs to a different economic head"
            )
        anchors = payload.get("anchors")
        if not isinstance(anchors, list) or len(anchors) < 4:
            raise OpmActiveCalibrationError("expected at least four hash-pinned OPM anchors")
        if sum(item.get("role") == "blind_holdout" for item in anchors) != 1:
            raise OpmActiveCalibrationError("exactly one blind holdout is required")
        if sum(item.get("role") == "blind_extension" for item in anchors) > 1:
            raise OpmActiveCalibrationError("at most one blind extension is supported")
        if any(len(str(item.get("schedule_hash") or "")) != 64 for item in anchors):
            raise OpmActiveCalibrationError("anchor schedule hash is invalid")
        deployment = payload["deployment"]
        validation = payload["validation"]
        return cls(
            slope=float(deployment["slope"]),
            intercept_rub=float(deployment["intercept_rub"]),
            raw_min_rub=float(deployment["raw_min_rub"]),
            raw_max_rub=float(deployment["raw_max_rub"]),
            economic_model_version=economic_model_version,
            version=version,
            blind_holdout_absolute_relative_error=float(
                validation["blind_holdout_absolute_relative_error"]
            ),
            blind_extension_absolute_relative_error=float(
                validation.get("blind_extension_absolute_relative_error", math.nan)
            ),
            loocv_mae_rub=float(validation["loocv_mae_rub"]),
        )
