
from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    ScenarioBaselineError,
)

import hashlib
from dataclasses import dataclass
from typing import (
    Protocol,
)

from backend.core.contracts import Constraints, Theta

from backend.contexts.optimization.domain.optimizer import (
    ObjectiveFunction,
    SearchReport,
    optimize,
)
from backend.contexts.robustness.application.battery import FragilityBattery, Scenario, Split
from backend.contexts.robustness.domain.regret import RegretReport, ScenarioOutcome


class ObjectiveFactory(Protocol):
    def __call__(self, constraints: Constraints, scenario: Scenario) -> ObjectiveFunction: ...


def scenario_seed(battery_seed: int, scenario_id: str) -> int:
    digest = hashlib.sha256(f"{battery_seed}:{scenario_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**31 - 1)


@dataclass(frozen=True, slots=True)
class BaselineSearch:
    scenario_id: str
    split: Split
    theta: Theta
    npv: float
    feasible: bool
    evaluations: int
    stop_reason: str
    seed: int
    underpowered: bool

    def __post_init__(self) -> None:
        if self.evaluations < 1:
            raise ScenarioBaselineError(
                f"{self.scenario_id}: бейзлайн без единой оценки"
            )


@dataclass(frozen=True, slots=True)
class RegretComputation:
    report: RegretReport
    searches: tuple[BaselineSearch, ...]
    nominal_theta: Theta

    @property
    def total_evaluations(self) -> int:
        return sum(search.evaluations for search in self.searches)

    @property
    def underpowered_scenarios(self) -> tuple[str, ...]:
        return tuple(
            search.scenario_id for search in self.searches if search.underpowered
        )

    def search_of(self, scenario_id: str) -> BaselineSearch:
        for search in self.searches:
            if search.scenario_id == scenario_id:
                return search
        raise ScenarioBaselineError(f"сценария {scenario_id!r} нет в отчёте")


def scenario_baseline(
    scenario: Scenario,
    factory: ObjectiveFactory,
    nominal_theta: Theta,
    *,
    battery_seed: int,
    max_evaluations: int,
    base_constraints: Constraints | None = None,
) -> tuple[BaselineSearch, float]:
    if max_evaluations < 1:
        raise ScenarioBaselineError(
            f"{scenario.scenario_id}: бюджет оценок {max_evaluations} < 1"
        )

    constraints = scenario.constraints(base_constraints)
    objective = factory(constraints, scenario)
    seed = scenario_seed(battery_seed, scenario.scenario_id)

    search: SearchReport = optimize(
        objective,
        nominal_theta,
        seed=seed,
        max_evaluations=max_evaluations,
    )

    ours = objective(nominal_theta)
    baseline_npv = search.best.result.objective

    return (
        BaselineSearch(
            scenario_id=scenario.scenario_id,
            split=scenario.split,
            theta=search.best.theta,
            npv=baseline_npv,
            feasible=search.best.result.feasible,
            evaluations=search.evaluations,
            stop_reason=search.stop_reason,
            seed=seed,
            underpowered=baseline_npv < ours.objective,
        ),
        ours.objective,
    )


def compute_regret(
    battery: FragilityBattery,
    factory: ObjectiveFactory,
    nominal_theta: Theta,
    *,
    threshold: float,
    max_evaluations_per_scenario: int,
    base_constraints: Constraints | None = None,
) -> RegretComputation:
    if not battery.scenarios:
        raise ScenarioBaselineError("пустая батарея ничего не меряет")

    searches: list[BaselineSearch] = []
    outcomes: list[ScenarioOutcome] = []

    for scenario in battery.scenarios:
        search, ours = scenario_baseline(
            scenario,
            factory,
            nominal_theta,
            battery_seed=battery.seed,
            max_evaluations=max_evaluations_per_scenario,
            base_constraints=base_constraints,
        )
        searches.append(search)
        outcomes.append(
            ScenarioOutcome(
                scenario_id=scenario.scenario_id,
                split=scenario.split,
                npv_ours=ours,
                npv_scenario_baseline=search.npv,
            )
        )

    return RegretComputation(
        report=RegretReport(
            outcomes=tuple(outcomes),
            threshold=threshold,
            battery_hash=battery.battery_hash(),
        ),
        searches=tuple(searches),
        nominal_theta=nominal_theta,
    )


def worst_scenarios(
    computation: RegretComputation, split: Split, limit: int = 3
) -> tuple[ScenarioOutcome, ...]:
    if limit < 1:
        raise ScenarioBaselineError(f"limit={limit} < 1")
    outcomes = computation.report.of(split)
    return tuple(
        sorted(outcomes, key=lambda outcome: -outcome.relative_regret)[:limit]
    )


def evaluation_budget(battery: FragilityBattery, per_scenario: int) -> int:
    if per_scenario < 1:
        raise ScenarioBaselineError(f"бюджет на сценарий {per_scenario} < 1")
    return len(battery.scenarios) * per_scenario
