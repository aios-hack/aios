from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.core.contracts import OptimizerResult, ScenarioViolation, Theta


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:

    regret: float
    feasible: bool
    what: str


class NominalObjective(Protocol):

    def __call__(self, theta: Theta) -> float: ...


class ScenarioEvaluator(Protocol):

    scenario_id: str

    def __call__(self, theta: Theta) -> ScenarioOutcome: ...


class ProvenanceSource(Protocol):

    def __call__(self, theta: Theta) -> dict[str, str]: ...


class Objective:

    def __init__(
        self,
        nominal: NominalObjective,
        battery: tuple[ScenarioEvaluator, ...],
        provenance: ProvenanceSource,
    ) -> None:
        ids = [scenario.scenario_id for scenario in battery]
        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        if duplicates:
            raise ValueError(f"scenario_id повторяется в батарее: {sorted(duplicates)}")
        self._nominal = nominal
        self._battery = battery
        self._provenance = provenance

    def __call__(self, theta: Theta) -> OptimizerResult:
        objective = self._nominal(theta)

        violations: list[ScenarioViolation] = []
        feasible = True
        for scenario in self._battery:
            outcome = scenario(theta)
            if not outcome.feasible:
                feasible = False
                violations.append(
                    ScenarioViolation(
                        scenario_id=scenario.scenario_id,
                        regret=outcome.regret,
                        what=outcome.what,
                    )
                )

        return OptimizerResult(
            objective=objective,
            feasible=feasible,
            violations_by_scenario=tuple(violations),
            provenance=self._provenance(theta),
        )
