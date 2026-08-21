"""Theta, OptimizerResult и Trace — решения политики. README.md §8."""

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
    """Вектор подгоняемых параметров, не более 10 суммарно по всем
    правилам, с объявленными границами. Единственное, что видит
    оптимизатор на входе."""

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
    regret: float  # просадка ЧДД против сценарного бейзлайна
    what: str  # что нарушено


@dataclass(frozen=True, slots=True)
class OptimizerResult:
    """Не скаляр — иначе исполнитель вынужден свернуть ограничение
    устойчивости в штраф, что запрещено (§13.3 базы знаний)."""

    objective: float  # ЧДД по Методике на номинальном сценарии
    feasible: bool  # выполнены ограничения батареи и Constraints
    violations_by_scenario: tuple[ScenarioViolation, ...]
    provenance: dict[str, str]  # хеши суррогата, Groups, датасета, seed


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """Одна запись на сработавшее правило. control_step 0…223 —
    control_step=224 (terminal_state) решений не несёт."""

    control_step: int
    well: str
    rule: Rule
    inputs: dict[str, float]
    decision: str
