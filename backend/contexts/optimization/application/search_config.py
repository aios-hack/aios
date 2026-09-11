from __future__ import annotations

from backend.contexts.optimization.domain.search_limits import (
    BASE_NPV,
    BUDGET,
    DEFAULT_FINAL_CAP,
    DEFAULT_SEARCH_CAP,
    INJECTION_TRANSFER_STEPS_M3_PER_DAY,
    MISSING_SIGMA,
    SEED,
    WATER_REPAIR_CEILING,
    WATER_REPAIR_MARGIN,
)

from backend.contexts.optimization.domain.errors import SearchRunError
from backend.shared.errors import ConfigurationError
from backend.shared.settings import Settings

try:
    _SETTINGS = Settings.from_env()
except ConfigurationError as _error:
    raise SearchRunError(_error.message) from _error

from backend.contexts.optimization.domain.errors import (
    SearchRunError,
)
import hashlib
from pathlib import Path
from backend.shared.paths import data_root


RESPONSE = data_root() / "base_case/response.json"


def _artifact_sha256(path: Path, name: str) -> str:
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise SearchRunError(
            f"провенанс поиска не собран: артефакт {name} по пути {path} "
            f"не читается — {error}"
        ) from error
    return hashlib.sha256(raw).hexdigest()


CONSTRAINTS = _SETTINGS.constraints_path


SEARCH_DIAGNOSTICS = _SETTINGS.search_diagnostics_path


SEARCH_RESULT = _SETTINGS.search_result_path


SEARCH_CAP = _SETTINGS.search_fixed_point_cap


FINAL_CAP = _SETTINGS.final_fixed_point_cap


RISK_AVERSION_BETA = _SETTINGS.risk_aversion_beta


__all__ = [
    "BASE_NPV",
    "BUDGET",
    "CONSTRAINTS",
    "DEFAULT_FINAL_CAP",
    "DEFAULT_SEARCH_CAP",
    "FINAL_CAP",
    "INJECTION_TRANSFER_STEPS_M3_PER_DAY",
    "MISSING_SIGMA",
    "RESPONSE",
    "RISK_AVERSION_BETA",
    "SEARCH_CAP",
    "SEARCH_DIAGNOSTICS",
    "SEARCH_RESULT",
    "SEED",
    "WATER_REPAIR_CEILING",
    "WATER_REPAIR_MARGIN",
]
