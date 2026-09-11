from __future__ import annotations

import math
from dataclasses import dataclass

from backend.core.contracts import N_INTERVALS


@dataclass(frozen=True, slots=True)
class RawWellStepPrediction:

    well: str
    control_step: int
    oil_mass_delta: float
    liquid_volume_delta: float
    injection_volume_delta: float
    liquid_rate: float
    injection_rate: float
    bhp: float

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
