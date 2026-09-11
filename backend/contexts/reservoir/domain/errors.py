from __future__ import annotations

from backend.shared.errors import (
    ValidationError,
)


class OpmDeckError(ValidationError):
    default_code = "reservoir.deck"


class PvtError(ValidationError):
    default_code = "reservoir.pvt"


class SummaryPlanError(ValidationError):
    default_code = "reservoir.summary_plan"


__all__ = [
    "OpmDeckError",
    "PvtError",
    "SummaryPlanError",
]
