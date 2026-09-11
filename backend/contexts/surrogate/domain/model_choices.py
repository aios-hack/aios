from __future__ import annotations



TARGET_PARAMETERIZATIONS: tuple[str, ...] = ("absolute", "watercut")


_SCENARIO_CONTEXTS: tuple[object, ...] = (False, True, "mean", "rich")


_LOSSES: tuple[str, ...] = ("smooth_l1", "mse", "huber")


_LR_SCHEDULES: tuple[str, ...] = ("none", "cosine")


_SELECTION_CRITERIA: tuple[str, ...] = ("loss", "money", "rank")


__all__ = [
    "TARGET_PARAMETERIZATIONS",
]
