from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.contexts.optimization.domain.errors import RuntimeArtifactError
from backend.shared.paths import project_root


CONSERVATIVE_OOD_THRESHOLD = 0.0
OOD_CALIBRATION_FORMAT = "aios.ood-calibration.v1"
DEFAULT_OOD_CALIBRATION = "out/ood-calibration.json"


@dataclass(frozen=True, slots=True)
class OodThresholdDecision:
    value: float
    origin: str
    calibrated: bool
    calibration_path: Path | None
    point_count: int
    detail: str

    def as_provenance(self) -> dict[str, str]:
        return {
            "ood_threshold": repr(self.value),
            "ood_threshold_origin": self.origin,
            "ood_threshold_calibrated": "true" if self.calibrated else "false",
            "ood_threshold_source": (
                "none" if self.calibration_path is None else str(self.calibration_path)
            ),
            "ood_threshold_point_count": str(self.point_count),
            "ood_threshold_detail": self.detail,
        }


def _parse_threshold_override(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeArtifactError(
            f"AIOS_OOD_THRESHOLD={raw!r} — the applicability domain threshold is given as a number"
        ) from error
    if not math.isfinite(value) or value < 0.0:
        raise RuntimeArtifactError(
            f"AIOS_OOD_THRESHOLD={raw!r} — the threshold must be finite and non-negative"
        )
    return value


def _read_calibration(path: Path) -> tuple[float, int, bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeArtifactError(
            f"OOD calibration artifact {path} is not readable: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != OOD_CALIBRATION_FORMAT:
        raise RuntimeArtifactError(f"unsupported OOD calibration artifact: {path}")
    threshold = payload.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise RuntimeArtifactError(f"{path}: the calibration threshold is not a number")
    value = float(threshold)
    if not math.isfinite(value) or value < 0.0:
        raise RuntimeArtifactError(
            f"{path}: calibration threshold {value} is not finite or is negative"
        )
    count = payload.get("point_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise RuntimeArtifactError(
            f"{path}: a calibration without a single measured point does not define a threshold"
        )
    return value, count, bool(payload.get("curve_is_reliable", False))


def resolve_ood_threshold(
    environ: Mapping[str, str] | None = None,
) -> OodThresholdDecision:
    env = os.environ if environ is None else environ
    override = env.get("AIOS_OOD_THRESHOLD")
    configured = env.get("AIOS_OOD_CALIBRATION_PATH")
    root_override = env.get("AIOS_PROJECT_ROOT")
    root = Path(root_override).expanduser().resolve() if root_override else project_root()
    calibration_path = (
        Path(configured) if configured else root / DEFAULT_OOD_CALIBRATION
    )
    if override is not None:
        value = _parse_threshold_override(override)
        return OodThresholdDecision(
            value=value,
            origin="environment-override",
            calibrated=False,
            calibration_path=calibration_path if calibration_path.is_file() else None,
            point_count=0,
            detail=(
                f"AIOS_OOD_THRESHOLD={override!r} overrides the calibration artifact; "
                "the threshold originates from an explicit operator override"
            ),
        )
    if configured and not calibration_path.is_file():
        raise RuntimeArtifactError(
            f"AIOS_OOD_CALIBRATION_PATH={configured} points at a missing "
            "calibration artifact"
        )
    if not calibration_path.is_file():
        return OodThresholdDecision(
            value=CONSERVATIVE_OOD_THRESHOLD,
            origin="uncalibrated-conservative-default",
            calibrated=False,
            calibration_path=None,
            point_count=0,
            detail=(
                f"calibration artifact {calibration_path} is absent: threshold "
                f"{CONSERVATIVE_OOD_THRESHOLD} is taken as conservative, "
                "NOT CALIBRATED — any candidate with even one node outside the "
                "training range is rejected"
            ),
        )
    value, count, reliable = _read_calibration(calibration_path)
    return OodThresholdDecision(
        value=value,
        origin=(
            "calibration-artifact"
            if reliable
            else "calibration-artifact/insufficient-points"
        ),
        calibrated=True,
        calibration_path=calibration_path,
        point_count=count,
        detail=(
            f"threshold {value} is taken from {calibration_path} over {count} measured "
            f"\"error versus OOD\" points"
            + ("" if reliable else "; too few points, the curve is unreliable")
        ),
    )

