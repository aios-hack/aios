from __future__ import annotations

from typing import Any

from backend.contexts.constraints.domain.constraints import CompensationPolicy

__all__ = [
    "COMPENSATION_NORM_MIN",
    "COMPENSATION_NORM_MAX",
    "COMPENSATION_SOURCE_DIAGNOSTIC",
    "COMPENSATION_BASIS_SURFACE",
    "COMPENSATION_BASIS_RESERVOIR",
    "compensation_norm",
    "reservoir_compensation",
]

COMPENSATION_NORM_MIN = 0.85
COMPENSATION_NORM_MAX = 1.15
COMPENSATION_SOURCE_DIAGNOSTIC = "diagnostic"
COMPENSATION_BASIS_SURFACE = "surface"
COMPENSATION_BASIS_RESERVOIR = "reservoir"


def compensation_norm(policy: CompensationPolicy) -> dict[str, Any]:
    minimum = COMPENSATION_NORM_MIN if policy.minimum is None else policy.minimum
    maximum = COMPENSATION_NORM_MAX if policy.maximum is None else policy.maximum
    return {
        "min": minimum,
        "max": maximum,
        "source": COMPENSATION_SOURCE_DIAGNOSTIC,
        "enforcement": policy.enforcement,
        "scope": policy.scope,
        "basis": COMPENSATION_BASIS_SURFACE,
    }


def reservoir_compensation(
    production: float,
    injection: float,
    reservoir_factors: dict[str, float] | None,
) -> float | None:
    if reservoir_factors is None:
        return None
    liquid_fvf = reservoir_factors.get("liquid")
    water_fvf = reservoir_factors.get("water")
    if liquid_fvf is None or water_fvf is None:
        return None
    if liquid_fvf <= 0 or water_fvf <= 0:
        return None
    withdrawal = production * liquid_fvf
    if withdrawal <= 0:
        return None
    return injection * water_fvf / withdrawal
