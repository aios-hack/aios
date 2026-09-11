from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MAX_THETA_PARAMS = 10


class Rule(Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
    R6 = "R6"
    R7 = "R7"


@dataclass(frozen=True, slots=True)
class Theta:

    values: dict[str, float]
    bounds: dict[str, tuple[float, float]]

    def __post_init__(self) -> None:
        if len(self.values) > MAX_THETA_PARAMS:
            raise ValueError(f"θ: {len(self.values)} параметров > {MAX_THETA_PARAMS}")
        missing_bounds = set(self.values) - set(self.bounds)
        if missing_bounds:
            raise ValueError(f"без объявленных границ: {missing_bounds}")


@dataclass(frozen=True, slots=True)
class ScenarioViolation:
    scenario_id: str
    regret: float
    what: str


@dataclass(frozen=True, slots=True)
class OptimizerResult:

    objective: float
    feasible: bool
    violations_by_scenario: tuple[ScenarioViolation, ...]
    provenance: dict[str, str]


@dataclass(frozen=True, slots=True)
class TraceEntry:

    control_step: int
    well: str
    rule: Rule
    inputs: dict[str, float]
    decision: str
