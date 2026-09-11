from __future__ import annotations

import math
from dataclasses import dataclass

from backend.contexts.schedule.domain.schedule import N_INTERVALS


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
                f"control_step={self.control_step} is outside 0…{N_INTERVALS - 1}"
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
                raise ValueError(f"{name}={value!r} is not finite")
            if value < 0:
                raise ValueError(f"{name}={value!r} is negative")


@dataclass(frozen=True, slots=True)
class RawModelOutput:

    canonical_schedule_hash: str
    wells: tuple[str, ...]
    nodes: tuple[RawWellStepPrediction, ...]

    def __post_init__(self) -> None:
        if not self.wells:
            raise ValueError("wells is empty")
        if len(set(self.wells)) != len(self.wells):
            raise ValueError("wells contains duplicates")
        expected = {(well, step) for well in self.wells for step in range(N_INTERVALS)}
        actual = {(node.well, node.control_step) for node in self.nodes}
        if actual != expected:
            missing = expected - actual
            extra = actual - expected
            raise ValueError(
                "nodes does not cover exactly wells × control_step 0…"
                f"{N_INTERVALS - 1}: missing {sorted(missing)[:5]}, "
                f"extra {sorted(extra)[:5]}"
            )
        if len(self.nodes) != len(expected):
            raise ValueError("nodes contains duplicate (well, control_step) entries")
