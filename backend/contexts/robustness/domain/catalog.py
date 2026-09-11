from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from backend.contexts.robustness.domain.battery import FragilityBattery, Scenario, Split
from backend.contexts.robustness.domain.perturbation import (
    InfrastructureLimit,
    InjectionCap,
    LiquidCap,
    Perturbation,
    ProductionFloor,
    WatercutCap,
    WellsOut,
)

BATTERY_VERSION = "battery-1"

REPAIR_SHARE = 0.12
OUTAGE_SPAN_STEPS = 6
TIGHT_SHARE = 0.7
HARD_SHARE = 0.5
FLOOR_SHARE = 0.8
WATERCUT_CAP = 0.95
WATERCUT_CAP_HARD = 0.9


@dataclass(frozen=True, slots=True)
class BatteryBasis:
    injectors: tuple[str, ...]
    producers: tuple[str, ...]
    injection_level_m3_per_day: float
    liquid_level_m3_per_day: float
    oil_level_t_per_day: float
    first_year: int
    last_year: int

    def __post_init__(self) -> None:
        if not self.injectors:
            raise ValueError("battery basis without injectors")
        if not self.producers:
            raise ValueError("battery basis without producers")
        if self.injection_level_m3_per_day <= 0.0:
            raise ValueError("the injection level is not positive")
        if self.liquid_level_m3_per_day <= 0.0:
            raise ValueError("the liquid level is not positive")
        if self.oil_level_t_per_day <= 0.0:
            raise ValueError("the oil level is not positive")
        if self.last_year <= self.first_year:
            raise ValueError(
                f"empty year range {self.first_year}…{self.last_year}"
            )

    def mid_year(self) -> int:
        return (self.first_year + self.last_year) // 2

    def years(self, since: int, until: int) -> tuple[int, ...]:
        if since < self.first_year or until > self.last_year:
            raise ValueError(
                f"years {since}…{until} fall outside the horizon "
                f"{self.first_year}…{self.last_year}"
            )
        return tuple(range(since, until + 1))


def _sample(wells: tuple[str, ...], share: float, offset: int) -> tuple[str, ...]:
    ordered = tuple(sorted(wells))
    count = max(1, int(len(ordered) * share))
    start = offset % len(ordered)
    picked = [ordered[(start + i) % len(ordered)] for i in range(count)]
    return tuple(sorted(set(picked)))


def default_scenarios(basis: BatteryBasis) -> tuple[Scenario, ...]:
    mid = basis.mid_year()
    early = basis.first_year + 1
    late = basis.last_year - 1
    return (
        Scenario(
            scenario_id="prs-producers-early",
            split=Split.DEV,
            description=(
                "a share of the producers goes out for workover in the early years, "
                "when the discount weighs the most"
            ),
            perturbations=(
                WellsOut(
                    wells=_sample(basis.producers, REPAIR_SHARE, 0),
                    control_step_from=0,
                    control_step_to=OUTAGE_SPAN_STEPS,
                ),
            ),
        ),
        Scenario(
            scenario_id="krs-injectors-mid",
            split=Split.DEV,
            description="failure at an injector pad in the middle of the horizon",
            perturbations=(
                WellsOut(
                    wells=_sample(basis.injectors, REPAIR_SHARE, 1),
                    control_step_from=OUTAGE_SPAN_STEPS,
                    control_step_to=OUTAGE_SPAN_STEPS * 2,
                ),
            ),
        ),
        Scenario(
            scenario_id="injection-cap-single-year",
            split=Split.DEV,
            description="the pad pump station runs short of water in one particular year",
            perturbations=(
                InjectionCap(
                    limits_by_year={
                        mid: basis.injection_level_m3_per_day * TIGHT_SHARE
                    }
                ),
            ),
        ),
        Scenario(
            scenario_id="liquid-cap-late",
            split=Split.DEV,
            description="the tank farm cannot take the liquid of the late years",
            perturbations=(
                LiquidCap(
                    limits_by_year={
                        year: basis.liquid_level_m3_per_day * TIGHT_SHARE
                        for year in basis.years(late - 1, late)
                    }
                ),
            ),
        ),
        Scenario(
            scenario_id="watercut-cap-field",
            split=Split.DEV,
            description="intake is limited by the watercut of the stream",
            perturbations=(
                WatercutCap(
                    limits_by_year={
                        year: WATERCUT_CAP for year in basis.years(mid, late)
                    }
                ),
            ),
        ),
        Scenario(
            scenario_id="production-floor-contract",
            split=Split.DEV,
            description="contractual floor on oil production",
            perturbations=(
                ProductionFloor(
                    floors_by_year={
                        year: basis.oil_level_t_per_day * FLOOR_SHARE
                        for year in basis.years(early, mid)
                    }
                ),
            ),
        ),
        Scenario(
            scenario_id="pipeline-capacity",
            split=Split.DEV,
            description="infrastructure limit: pipeline throughput",
            perturbations=(
                InfrastructureLimit(
                    entries={
                        "pipeline_liquid_m3_per_day": (
                            basis.liquid_level_m3_per_day * TIGHT_SHARE
                        )
                    }
                ),
            ),
        ),
        Scenario(
            scenario_id="holdout-outage-and-injection-cap",
            split=Split.HOLDOUT,
            description=(
                "a well stock outage overlaps the water shortage of the same year — "
                "a combination θ were never fitted on"
            ),
            perturbations=(
                WellsOut(
                    wells=_sample(basis.producers, REPAIR_SHARE, 3),
                    control_step_from=OUTAGE_SPAN_STEPS * 2,
                    control_step_to=OUTAGE_SPAN_STEPS * 3,
                ),
                InjectionCap(
                    limits_by_year={
                        year: basis.injection_level_m3_per_day * HARD_SHARE
                        for year in basis.years(mid, mid + 1)
                    }
                ),
            ),
        ),
        Scenario(
            scenario_id="holdout-liquid-and-watercut",
            split=Split.HOLDOUT,
            description="a hard liquid limit under a hard watercut limit",
            perturbations=(
                LiquidCap(
                    limits_by_year={
                        year: basis.liquid_level_m3_per_day * HARD_SHARE
                        for year in basis.years(early, mid)
                    }
                ),
                WatercutCap(
                    limits_by_year={
                        year: WATERCUT_CAP_HARD for year in basis.years(early, mid)
                    }
                ),
            ),
        ),
        Scenario(
            scenario_id="holdout-floor-and-infrastructure",
            split=Split.HOLDOUT,
            description=(
                "a production floor under an infrastructure limit on injection"
            ),
            perturbations=(
                ProductionFloor(
                    floors_by_year={
                        year: basis.oil_level_t_per_day * FLOOR_SHARE
                        for year in basis.years(mid, late)
                    }
                ),
                InfrastructureLimit(
                    entries={
                        "pump_station_injection_m3_per_day": (
                            basis.injection_level_m3_per_day * HARD_SHARE
                        )
                    }
                ),
            ),
        ),
    )


def default_battery(basis: BatteryBasis, seed: int) -> FragilityBattery:
    return FragilityBattery(
        scenarios=default_scenarios(basis),
        seed=seed,
        version=BATTERY_VERSION,
    )


def battery_of(
    scenarios: Sequence[Scenario], seed: int, version: str
) -> FragilityBattery:
    return FragilityBattery(
        scenarios=tuple(scenarios), seed=seed, version=version
    )


def perturbations_of(scenario: Scenario) -> tuple[Perturbation, ...]:
    return scenario.perturbations
