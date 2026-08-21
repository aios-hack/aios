from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from aios_backend.domain.robustness.battery import FragilityBattery, Scenario, Split
from aios_backend.domain.robustness.perturbation import (
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
            raise ValueError("основа батареи без нагнетательных")
        if not self.producers:
            raise ValueError("основа батареи без добывающих")
        if self.injection_level_m3_per_day <= 0.0:
            raise ValueError("уровень закачки не положителен")
        if self.liquid_level_m3_per_day <= 0.0:
            raise ValueError("уровень жидкости не положителен")
        if self.oil_level_t_per_day <= 0.0:
            raise ValueError("уровень нефти не положителен")
        if self.last_year <= self.first_year:
            raise ValueError(
                f"пустой диапазон лет {self.first_year}…{self.last_year}"
            )

    def mid_year(self) -> int:
        return (self.first_year + self.last_year) // 2

    def years(self, since: int, until: int) -> tuple[int, ...]:
        if since < self.first_year or until > self.last_year:
            raise ValueError(
                f"годы {since}…{until} выходят за горизонт "
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
                "часть добывающих выпадает на ПРС в ранние годы, "
                "когда дисконт весит больше всего"
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
            description="авария на кусте нагнетательных в середине горизонта",
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
            description="воды на кустовой насосной не хватает один конкретный год",
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
            description="товарный парк не принимает жидкость поздних лет",
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
            description="приёмка ограничена обводнённостью потока",
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
            description="контрактная нижняя граница добычи нефти",
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
            description="инфраструктурный лимит: пропускная способность трубопровода",
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
                "выпадение фонда накладывается на дефицит воды того же года — "
                "комбинация, на которую θ не подгонялись"
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
            description="жёсткий лимит жидкости при жёстком пределе обводнённости",
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
                "нижняя граница добычи при инфраструктурном лимите на закачку"
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
