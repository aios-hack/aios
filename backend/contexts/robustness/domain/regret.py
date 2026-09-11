from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from backend.contexts.policy.domain.policy import ScenarioViolation

from backend.contexts.robustness.domain.battery import FragilityBattery, Scenario, Split


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario_id: str
    split: Split
    npv_ours: float
    npv_scenario_baseline: float

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("outcome without a scenario identifier")

    @property
    def regret(self) -> float:
        return self.npv_scenario_baseline - self.npv_ours

    @property
    def relative_regret(self) -> float:
        denominator = abs(self.npv_scenario_baseline)
        if denominator == 0.0:
            raise ValueError(
                f"{self.scenario_id}: the scenario baseline is zero, "
                f"relative regret is undefined"
            )
        return self.regret / denominator


@dataclass(frozen=True, slots=True)
class RegretReport:
    outcomes: tuple[ScenarioOutcome, ...]
    threshold: float
    battery_hash: str

    def __post_init__(self) -> None:
        if self.threshold < 0.0:
            raise ValueError(f"the regret threshold {self.threshold} is negative")
        identifiers = [o.scenario_id for o in self.outcomes]
        duplicates = sorted(
            {name for name in identifiers if identifiers.count(name) > 1}
        )
        if duplicates:
            raise ValueError(f"duplicate scenario outcomes: {duplicates}")

    def of(self, split: Split) -> tuple[ScenarioOutcome, ...]:
        return tuple(o for o in self.outcomes if o.split is split)

    def violations(self, split: Split) -> tuple[ScenarioViolation, ...]:
        return tuple(
            ScenarioViolation(
                scenario_id=outcome.scenario_id,
                regret=outcome.regret,
                what=(
                    f"relative regret {outcome.relative_regret:.4f} "
                    f"exceeds the threshold {self.threshold:.4f}"
                ),
            )
            for outcome in self.of(split)
            if outcome.relative_regret > self.threshold
        )

    def feasible(self, split: Split = Split.DEV) -> bool:
        return not self.violations(split)

    def worst(self, split: Split) -> ScenarioOutcome:
        outcomes = self.of(split)
        if not outcomes:
            raise ValueError(f"split «{split.value}» has no outcomes")
        return max(outcomes, key=lambda o: o.relative_regret)

    def by_scenario(self, split: Split) -> Mapping[str, float]:
        return {o.scenario_id: o.relative_regret for o in self.of(split)}


def optimization_view(report: RegretReport) -> tuple[bool, tuple[ScenarioViolation, ...]]:
    return report.feasible(Split.DEV), report.violations(Split.DEV)


def holdout_view(report: RegretReport) -> tuple[bool, tuple[ScenarioViolation, ...]]:
    return report.feasible(Split.HOLDOUT), report.violations(Split.HOLDOUT)


def covers_battery(report: RegretReport, battery: FragilityBattery) -> bool:
    return {o.scenario_id for o in report.outcomes} == {
        s.scenario_id for s in battery.scenarios
    }


def scenario_of(battery: FragilityBattery, outcome: ScenarioOutcome) -> Scenario:
    scenario = battery.by_id(outcome.scenario_id)
    if scenario.split is not outcome.split:
        raise ValueError(
            f"{outcome.scenario_id}: the outcome is assigned to «{outcome.split.value}», "
            f"while the battery declares «{scenario.split.value}»"
        )
    return scenario
