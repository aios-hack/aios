from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    SearchRunError,
)
import json
import math
import os
from dataclasses import (
    dataclass,
)
from pathlib import Path
from typing import (
    Mapping,
)


OOD_CALIBRATION_FORMAT = "aios.ood-calibration.v1"


DEFAULT_OOD_CALIBRATION = "out/ood-calibration.json"


CONSERVATIVE_OOD_THRESHOLD = 0.0


@dataclass(frozen=True, slots=True)
class OodThreshold:
    value: float
    origin: str
    calibrated: bool
    source: str
    point_count: int
    detail: str

    def as_provenance(self) -> dict[str, str]:
        return {
            "ood_threshold": repr(self.value),
            "ood_threshold_origin": self.origin,
            "ood_threshold_calibrated": "true" if self.calibrated else "false",
            "ood_threshold_source": self.source,
            "ood_threshold_point_count": str(self.point_count),
            "ood_threshold_detail": self.detail,
        }


def _ood_threshold_decision(
    environ: Mapping[str, str] | None = None,
) -> OodThreshold:
    env = os.environ if environ is None else environ
    override = env.get("AIOS_OOD_THRESHOLD")
    configured = env.get("AIOS_OOD_CALIBRATION_PATH")
    root = env.get("AIOS_PROJECT_ROOT")
    calibration_path = (
        Path(configured)
        if configured
        else (Path(root) if root else Path.cwd()) / DEFAULT_OOD_CALIBRATION
    )
    if override is not None:
        try:
            value = float(override)
        except ValueError as error:
            raise SearchRunError(
                f"AIOS_OOD_THRESHOLD={override!r} — the applicability domain threshold "
                "is given as a number"
            ) from error
        if not math.isfinite(value) or value < 0.0:
            raise SearchRunError(
                f"AIOS_OOD_THRESHOLD={override!r} — the threshold must be finite "
                "and non-negative"
            )
        return OodThreshold(
            value=value,
            origin="environment-override",
            calibrated=False,
            source="none" if not calibration_path.is_file() else str(calibration_path),
            point_count=0,
            detail=(
                f"AIOS_OOD_THRESHOLD={override!r} overrides the calibration artifact; "
                "the threshold originates from an explicit operator override"
            ),
        )
    if configured and not calibration_path.is_file():
        raise SearchRunError(
            f"AIOS_OOD_CALIBRATION_PATH={configured} points at a missing "
            "calibration artifact"
        )
    if not calibration_path.is_file():
        return OodThreshold(
            value=CONSERVATIVE_OOD_THRESHOLD,
            origin="uncalibrated-conservative-default",
            calibrated=False,
            source="none",
            point_count=0,
            detail=(
                f"calibration artifact {calibration_path} is absent: threshold "
                f"{CONSERVATIVE_OOD_THRESHOLD} is taken as conservative, "
                "NOT CALIBRATED — any candidate with even one node outside the "
                "training range is rejected"
            ),
        )
    try:
        payload = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SearchRunError(
            f"OOD calibration artifact {calibration_path} is not readable: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != OOD_CALIBRATION_FORMAT:
        raise SearchRunError(
            f"unsupported OOD calibration artifact: {calibration_path}"
        )
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise SearchRunError(f"{calibration_path}: the calibration threshold is not a number")
    value = float(threshold)
    if not math.isfinite(value) or value < 0.0:
        raise SearchRunError(
            f"{calibration_path}: calibration threshold {value} is not finite or is negative"
        )
    count = payload.get("point_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise SearchRunError(
            f"{calibration_path}: a calibration without a single measured point "
            "does not define a threshold"
        )
    reliable = bool(payload.get("curve_is_reliable", False))
    return OodThreshold(
        value=value,
        origin=(
            "calibration-artifact"
            if reliable
            else "calibration-artifact/insufficient-points"
        ),
        calibrated=True,
        source=str(calibration_path),
        point_count=count,
        detail=(
            f"threshold {value} is taken from {calibration_path} over {count} measured "
            f"\"error versus OOD\" points"
            + ("" if reliable else "; too few points, the curve is unreliable")
        ),
    )


def _soft_penalty_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    raw = env.get("AIOS_OOD_SOFT_PENALTY")
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("", "0", "false", "no", "off"):
        return False
    raise SearchRunError(
        f"AIOS_OOD_SOFT_PENALTY={raw!r} — enabling the soft penalty is given as "
        "a boolean value (1/0, true/false, yes/no, on/off)"
    )


def _soft_penalty_rate(environ: Mapping[str, str] | None = None) -> float:
    env = os.environ if environ is None else environ
    raw = env.get("AIOS_OOD_PENALTY_PER_UNIT", "1.0")
    try:
        value = float(raw)
    except ValueError as error:
        raise SearchRunError(
            f"AIOS_OOD_PENALTY_PER_UNIT={raw!r} — the soft penalty rate is given as a number"
        ) from error
    if not math.isfinite(value) or value <= 0.0:
        raise SearchRunError(
            f"AIOS_OOD_PENALTY_PER_UNIT={raw!r} — the rate must be finite "
            "and positive"
        )
    return value


__all__ = [
    "CONSERVATIVE_OOD_THRESHOLD",
    "DEFAULT_OOD_CALIBRATION",
    "OOD_CALIBRATION_FORMAT",
    "OodThreshold",
]
