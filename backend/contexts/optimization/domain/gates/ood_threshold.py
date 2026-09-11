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
                f"AIOS_OOD_THRESHOLD={override!r} — порог области применимости "
                "задаётся числом"
            ) from error
        if not math.isfinite(value) or value < 0.0:
            raise SearchRunError(
                f"AIOS_OOD_THRESHOLD={override!r} — порог обязан быть конечным "
                "и неотрицательным"
            )
        return OodThreshold(
            value=value,
            origin="environment-override",
            calibrated=False,
            source="none" if not calibration_path.is_file() else str(calibration_path),
            point_count=0,
            detail=(
                f"AIOS_OOD_THRESHOLD={override!r} перекрывает артефакт калибровки; "
                "происхождение порога — явное переопределение оператором"
            ),
        )
    if configured and not calibration_path.is_file():
        raise SearchRunError(
            f"AIOS_OOD_CALIBRATION_PATH={configured} указывает на отсутствующий "
            "артефакт калибровки"
        )
    if not calibration_path.is_file():
        return OodThreshold(
            value=CONSERVATIVE_OOD_THRESHOLD,
            origin="uncalibrated-conservative-default",
            calibrated=False,
            source="none",
            point_count=0,
            detail=(
                f"артефакт калибровки {calibration_path} отсутствует: порог "
                f"{CONSERVATIVE_OOD_THRESHOLD} взят как консервативный, "
                "НЕ ОТКАЛИБРОВАН — отвергается любой кандидат хоть с одним узлом "
                "вне обучающего диапазона"
            ),
        )
    try:
        payload = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SearchRunError(
            f"артефакт калибровки OOD {calibration_path} не читается: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != OOD_CALIBRATION_FORMAT:
        raise SearchRunError(
            f"неподдерживаемый артефакт калибровки OOD: {calibration_path}"
        )
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise SearchRunError(f"{calibration_path}: порог калибровки не число")
    value = float(threshold)
    if not math.isfinite(value) or value < 0.0:
        raise SearchRunError(
            f"{calibration_path}: порог калибровки {value} не конечен или отрицателен"
        )
    count = payload.get("point_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise SearchRunError(
            f"{calibration_path}: калибровка без единой измеренной точки "
            "не задаёт порог"
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
            f"порог {value} взят из {calibration_path} по {count} измеренным "
            f"точкам «ошибка против OOD»"
            + ("" if reliable else "; точек мало, кривая ненадёжна")
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
        f"AIOS_OOD_SOFT_PENALTY={raw!r} — включение мягкого штрафа задаётся "
        "булевым значением (1/0, true/false, yes/no, on/off)"
    )


def _soft_penalty_rate(environ: Mapping[str, str] | None = None) -> float:
    env = os.environ if environ is None else environ
    raw = env.get("AIOS_OOD_PENALTY_PER_UNIT", "1.0")
    try:
        value = float(raw)
    except ValueError as error:
        raise SearchRunError(
            f"AIOS_OOD_PENALTY_PER_UNIT={raw!r} — ставка мягкого штрафа задаётся числом"
        ) from error
    if not math.isfinite(value) or value <= 0.0:
        raise SearchRunError(
            f"AIOS_OOD_PENALTY_PER_UNIT={raw!r} — ставка обязана быть конечной "
            "и положительной"
        )
    return value


__all__ = [
    "CONSERVATIVE_OOD_THRESHOLD",
    "DEFAULT_OOD_CALIBRATION",
    "OOD_CALIBRATION_FORMAT",
    "OodThreshold",
]
