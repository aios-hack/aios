from __future__ import annotations


BASE_NPV = 11_873_122_324.91


SEED = 20260816


DEFAULT_SEARCH_CAP = 2


DEFAULT_FINAL_CAP = 8


BUDGET = 120


MISSING_SIGMA = (
    "β is set, but the model gives no spread: an ensemble is required"
)


WATER_REPAIR_MARGIN = 0.98


WATER_REPAIR_CEILING = 0.95


INJECTION_TRANSFER_STEPS_M3_PER_DAY: tuple[float, ...] = (25.0, 50.0, 100.0)


__all__ = [
    "BASE_NPV",
    "BUDGET",
    "DEFAULT_FINAL_CAP",
    "DEFAULT_SEARCH_CAP",
    "INJECTION_TRANSFER_STEPS_M3_PER_DAY",
    "MISSING_SIGMA",
    "SEED",
    "WATER_REPAIR_CEILING",
    "WATER_REPAIR_MARGIN",
]
