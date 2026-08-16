from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from contracts import Constraints, WellOutage


class PerturbationKind(Enum):
    WELL_OUTAGE = "WELL_OUTAGE"
    INJECTION_LIMIT = "INJECTION_LIMIT"
    LIQUID_LIMIT = "LIQUID_LIMIT"
    PRODUCTION_FLOOR = "PRODUCTION_FLOOR"
    WATERCUT_LIMIT = "WATERCUT_LIMIT"
    INFRASTRUCTURE_LIMIT = "INFRASTRUCTURE_LIMIT"


ORGANIZER_KINDS: tuple[PerturbationKind, ...] = (
    PerturbationKind.WELL_OUTAGE,
    PerturbationKind.INJECTION_LIMIT,
    PerturbationKind.LIQUID_LIMIT,
    PerturbationKind.PRODUCTION_FLOOR,
    PerturbationKind.WATERCUT_LIMIT,
    PerturbationKind.INFRASTRUCTURE_LIMIT,
)

KIND_SOURCE: dict[PerturbationKind, str] = {
    PerturbationKind.WELL_OUTAGE: "выпадение скважин на ремонт или аварию",
    PerturbationKind.INJECTION_LIMIT: "ограничение по закачке в конкретном году",
    PerturbationKind.LIQUID_LIMIT: "ограничение по жидкости",
    PerturbationKind.PRODUCTION_FLOOR: "нижняя граница добычи",
    PerturbationKind.WATERCUT_LIMIT: "ограничение по обводнённости",
    PerturbationKind.INFRASTRUCTURE_LIMIT: "инфраструктурные лимиты",
}


class Perturbation(Protocol):
    kind: PerturbationKind

    def apply(self, base: Constraints) -> Constraints: ...


@dataclass(frozen=True, slots=True)
class WellsOut:
    wells: tuple[str, ...]
    control_step_from: int
    control_step_to: int
    kind: PerturbationKind = PerturbationKind.WELL_OUTAGE

    def __post_init__(self) -> None:
        if not self.wells:
            raise ValueError("выпадение без скважин — не возмущение")
        if self.control_step_to <= self.control_step_from:
            raise ValueError(
                f"пустое окно недоступности "
                f"{self.control_step_from}…{self.control_step_to}"
            )

    def apply(self, base: Constraints) -> Constraints:
        added = tuple(
            WellOutage(
                well=well,
                control_step_from=self.control_step_from,
                control_step_to=self.control_step_to,
            )
            for well in sorted(self.wells)
        )
        return replace(base, well_outages=base.well_outages + added)


@dataclass(frozen=True, slots=True)
class InjectionCap:
    limits_by_year: dict[int, float]
    kind: PerturbationKind = PerturbationKind.INJECTION_LIMIT

    def __post_init__(self) -> None:
        _reject_empty(self.limits_by_year, "лимит закачки")
        _reject_negative(self.limits_by_year, "лимит закачки")

    def apply(self, base: Constraints) -> Constraints:
        return replace(
            base,
            injection_limits=_tightened(base.injection_limits, self.limits_by_year),
        )


@dataclass(frozen=True, slots=True)
class LiquidCap:
    limits_by_year: dict[int, float]
    kind: PerturbationKind = PerturbationKind.LIQUID_LIMIT

    def __post_init__(self) -> None:
        _reject_empty(self.limits_by_year, "лимит жидкости")
        _reject_negative(self.limits_by_year, "лимит жидкости")

    def apply(self, base: Constraints) -> Constraints:
        return replace(
            base,
            liquid_limits=_tightened(base.liquid_limits, self.limits_by_year),
        )


@dataclass(frozen=True, slots=True)
class ProductionFloor:
    floors_by_year: dict[int, float]
    kind: PerturbationKind = PerturbationKind.PRODUCTION_FLOOR

    def __post_init__(self) -> None:
        _reject_empty(self.floors_by_year, "нижняя граница добычи")
        _reject_negative(self.floors_by_year, "нижняя граница добычи")

    def apply(self, base: Constraints) -> Constraints:
        merged = dict(base.production_floors)
        for year, floor in self.floors_by_year.items():
            merged[year] = max(merged.get(year, floor), floor)
        return replace(base, production_floors=merged)


@dataclass(frozen=True, slots=True)
class WatercutCap:
    limits_by_year: dict[int, float]
    kind: PerturbationKind = PerturbationKind.WATERCUT_LIMIT

    def __post_init__(self) -> None:
        _reject_empty(self.limits_by_year, "ограничение по обводнённости")
        for year, share in self.limits_by_year.items():
            if not (0.0 <= share <= 1.0):
                raise ValueError(f"{year}: обводнённость {share} вне [0, 1]")

    def apply(self, base: Constraints) -> Constraints:
        return replace(
            base,
            watercut_limits=_tightened(base.watercut_limits, self.limits_by_year),
        )


@dataclass(frozen=True, slots=True)
class InfrastructureLimit:
    entries: dict[str, object]
    kind: PerturbationKind = PerturbationKind.INFRASTRUCTURE_LIMIT

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("инфраструктурное ограничение без содержимого")

    def apply(self, base: Constraints) -> Constraints:
        merged = dict(base.infrastructure)
        clashes = set(merged) & set(self.entries)
        if clashes:
            raise ValueError(
                f"инфраструктурные ключи уже заняты базовым документом: "
                f"{sorted(clashes)}"
            )
        merged.update(self.entries)
        return replace(base, infrastructure=merged)


def _reject_empty(mapping: dict[int, float], what: str) -> None:
    if not mapping:
        raise ValueError(f"{what} без единого года — не возмущение")


def _reject_negative(mapping: dict[int, float], what: str) -> None:
    for year, value in mapping.items():
        if value < 0.0:
            raise ValueError(f"{year}: {what} отрицателен ({value})")


def _tightened(
    base: dict[int, float], added: dict[int, float]
) -> dict[int, float]:
    merged = dict(base)
    for year, value in added.items():
        merged[year] = min(merged.get(year, value), value)
    return merged
