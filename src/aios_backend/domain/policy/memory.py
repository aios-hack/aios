from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from aios_backend.core.contracts import EspCatalogEntry, Role

NO_EVENT = -1


@dataclass(frozen=True, slots=True)
class WellMemory:
    months_in_loss: int = 0
    months_in_profit: int = 0
    last_switch_step: int = NO_EVENT
    last_setpoint_change_step: int = NO_EVENT
    esp_nominal_m3_per_day: float = 0.0
    converted_to_injection: bool = False

    def __post_init__(self) -> None:
        if self.months_in_loss < 0 or self.months_in_profit < 0:
            raise ValueError("счётчик месяцев отрицателен")
        if self.esp_nominal_m3_per_day < 0.0:
            raise ValueError("типоразмер ЭЦН отрицателен")

    def steps_since_switch(self, control_step: int) -> int | None:
        if self.last_switch_step == NO_EVENT:
            return None
        return control_step - self.last_switch_step

    def with_loss(self) -> "WellMemory":
        return replace(
            self, months_in_loss=self.months_in_loss + 1, months_in_profit=0
        )

    def with_profit(self) -> "WellMemory":
        return replace(
            self, months_in_profit=self.months_in_profit + 1, months_in_loss=0
        )

    def switched_at(self, control_step: int) -> "WellMemory":
        return replace(
            self,
            last_switch_step=control_step,
            months_in_loss=0,
            months_in_profit=0,
        )

    def with_esp(self, nominal_m3_per_day: float) -> "WellMemory":
        if nominal_m3_per_day < self.esp_nominal_m3_per_day:
            raise ValueError(
                f"типоразмер ЭЦН не понижается: {self.esp_nominal_m3_per_day} "
                f"→ {nominal_m3_per_day}; храповик необратим"
            )
        return replace(self, esp_nominal_m3_per_day=nominal_m3_per_day)

    def converted_at(self, control_step: int) -> "WellMemory":
        return replace(
            self, converted_to_injection=True, last_switch_step=control_step
        )


@dataclass(frozen=True, slots=True)
class PolicyMemory:
    wells: dict[str, WellMemory] = field(default_factory=dict)

    def of(self, well: str) -> WellMemory:
        return self.wells.get(well, WellMemory())

    def updated(self, well: str, memory: WellMemory) -> "PolicyMemory":
        merged = dict(self.wells)
        merged[well] = memory
        return PolicyMemory(wells=merged)

    def merged(self, updates: Mapping[str, WellMemory]) -> "PolicyMemory":
        merged = dict(self.wells)
        merged.update(updates)
        return PolicyMemory(wells=merged)


def esp_size_for(
    catalog: tuple[EspCatalogEntry, ...], liquid_rate_m3_per_day: float
) -> EspCatalogEntry:
    if not catalog:
        raise ValueError(
            "каталог ЭЦН пуст: типоразмер выводится из каталога нормативов, "
            "а не назначается числом в правиле"
        )
    for entry in sorted(catalog, key=lambda e: e.nominal):
        if entry.interval_low <= liquid_rate_m3_per_day <= entry.interval_high:
            return entry
    highest = max(catalog, key=lambda e: e.nominal)
    if liquid_rate_m3_per_day > highest.interval_high:
        return highest
    return min(catalog, key=lambda e: e.nominal)


def esp_upgrade_cost_rub(
    current_nominal_m3_per_day: float,
    target: EspCatalogEntry,
    swap_opex_rub: float,
) -> float:
    if target.nominal <= current_nominal_m3_per_day:
        return 0.0
    return target.cost_rub + swap_opex_rub


def is_producer(role: Role) -> bool:
    return role is Role.PROD
