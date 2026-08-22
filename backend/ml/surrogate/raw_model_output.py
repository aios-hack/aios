"""Raw surrogate prediction shape — task 33's contract with task 34.

Owned entirely by ``surrogate/``, not ``contracts/``: only the adapter
(``surrogate.adapter``, this task) and the model that produces this shape
(task 34, not built yet) ever see it. It is deliberately narrow — one node
per ``(well, control_step)`` carrying only the six numeric channels the
adapter needs (docs/context/08_contracts.md §5.1.1): the model never emits
``oil_rate`` (achievability-trap, §5.1.1) or ``active_control_mode``
(diagnostic-only, derived by the adapter via the same fallback rule
``bridge.response_loader`` uses when ``WMCTL`` is unavailable).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.core.contracts import N_INTERVALS


@dataclass(frozen=True, slots=True)
class RawWellStepPrediction:
    """One ``(well, control_step)`` node of the model's raw output.

    ``oil_mass_delta``/``liquid_volume_delta``/``injection_volume_delta`` map
    straight onto ``IntervalResponse`` (money target, §5.1.1: predicted as
    volume, not rate×days). ``liquid_rate``/``injection_rate``/``bhp`` map
    onto the predicted half of ``StateAtDate`` (§5.1).
    """

    well: str
    control_step: int  # 0…223, contracts.N_INTERVALS axis
    oil_mass_delta: float  # т
    liquid_volume_delta: float  # м³
    injection_volume_delta: float  # м³
    liquid_rate: float  # м³/сут
    injection_rate: float  # м³/сут
    bhp: float  # бар

    def __post_init__(self) -> None:
        if not (0 <= self.control_step <= N_INTERVALS - 1):
            raise ValueError(
                f"control_step={self.control_step} вне 0…{N_INTERVALS - 1}"
            )
        for name in (
            "oil_mass_delta",
            "liquid_volume_delta",
            "injection_volume_delta",
            "liquid_rate",
            "injection_rate",
            "bhp",
        ):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"{name}={value!r} не конечно")
            if value < 0:
                raise ValueError(f"{name}={value!r} отрицательно")


@dataclass(frozen=True, slots=True)
class RawModelOutput:
    """Model output for one candidate schedule, all wells, all 224 steps.

    ``canonical_schedule_hash`` pins the prediction to the schedule it was
    made for — the adapter checks it against ``hash_schedule(schedule)``, not
    trusted blindly. ``nodes`` carries no ordering requirement: the adapter
    re-keys by ``(well, control_step)`` itself.
    """

    canonical_schedule_hash: str
    wells: tuple[str, ...]
    nodes: tuple[RawWellStepPrediction, ...]

    def __post_init__(self) -> None:
        if not self.wells:
            raise ValueError("wells пуст")
        if len(set(self.wells)) != len(self.wells):
            raise ValueError("wells содержит дубликаты")
        expected = {(well, step) for well in self.wells for step in range(N_INTERVALS)}
        actual = {(node.well, node.control_step) for node in self.nodes}
        if actual != expected:
            missing = expected - actual
            extra = actual - expected
            raise ValueError(
                "nodes не покрывает ровно wells × control_step 0…"
                f"{N_INTERVALS - 1}: недостаёт {sorted(missing)[:5]}, "
                f"лишнее {sorted(extra)[:5]}"
            )
        if len(self.nodes) != len(expected):
            raise ValueError("nodes содержит дублирующиеся (well, control_step)")
