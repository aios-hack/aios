from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

WATER_SUPPLY_UNLIMITED = "water_supply_unlimited"
WATER_REINJECTION_FRACTION = "water_reinjection_fraction"
WATER_REINJECTION_LAG_STEPS = "water_reinjection_lag_steps"
EXTERNAL_WATER_M3_PER_DAY = "external_water_m3_per_day"
WATER_SAFETY_FACTOR = "water_safety_factor"
COMPENSATION_MIN = "compensation_min"
COMPENSATION_MAX = "compensation_max"
COMPENSATION_ENFORCEMENT = "compensation_enforcement"
COMPENSATION_SCOPE = "compensation_scope"
BHP_PRODUCER_MIN_BAR = "bhp_producer_min_bar"
BHP_INJECTOR_MAX_BAR = "bhp_injector_max_bar"
PRESSURE_FLOOR_BAR = "pressure_floor_bar"
PRESSURE_CEILING_BAR = "pressure_ceiling_bar"
REGION_PRESSURE_FLOOR_BAR = "region_pressure_floor_bar"
REGION_PRESSURE_CEILING_BAR = "region_pressure_ceiling_bar"

SOURCE_SUFFIX = "_source"

SOURCE_ORGANIZER = "organizer"
SOURCE_DIAGNOSTIC = "diagnostic"
SOURCE_ASSUMPTION = "assumption"

CONSTRAINT_SOURCES: frozenset[str] = frozenset(
    {SOURCE_ORGANIZER, SOURCE_DIAGNOSTIC, SOURCE_ASSUMPTION}
)

SOURCE_LABELS: dict[str, str] = {
    SOURCE_ORGANIZER: "organizers' condition",
    SOURCE_DIAGNOSTIC: "diagnostic reference",
    SOURCE_ASSUMPTION: "our own assumption",
}

DEFAULT_WATER_SAFETY_FACTOR = 1.0
DEFAULT_BHP_PRODUCER_MIN_BAR = 50.0
DEFAULT_BHP_INJECTOR_MAX_BAR = 300.0

BLOCKING_INFRASTRUCTURE_KEYS: tuple[str, ...] = (
    WATER_SUPPLY_UNLIMITED,
    WATER_REINJECTION_FRACTION,
    WATER_REINJECTION_LAG_STEPS,
    EXTERNAL_WATER_M3_PER_DAY,
    BHP_PRODUCER_MIN_BAR,
    BHP_INJECTOR_MAX_BAR,
    PRESSURE_FLOOR_BAR,
    PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    REGION_PRESSURE_CEILING_BAR,
)

DIAGNOSTIC_INFRASTRUCTURE_KEYS: tuple[str, ...] = (
    WATER_SAFETY_FACTOR,
    COMPENSATION_MIN,
    COMPENSATION_MAX,
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_SCOPE,
)

SOURCED_INFRASTRUCTURE_KEYS: tuple[str, ...] = (
    BLOCKING_INFRASTRUCTURE_KEYS + DIAGNOSTIC_INFRASTRUCTURE_KEYS
)

DEFAULT_SOURCES: dict[str, str] = {
    BHP_PRODUCER_MIN_BAR: SOURCE_ORGANIZER,
    BHP_INJECTOR_MAX_BAR: SOURCE_ORGANIZER,
}

COMPENSATION_ENFORCEMENTS = frozenset({"diagnostic", "hard"})
COMPENSATION_SCOPES = frozenset({"field", "groups", "field_and_groups"})


def source_key(key: str) -> str:
    return f"{key}{SOURCE_SUFFIX}"


@dataclass(frozen=True, slots=True)
class WellOutage:
    well: str
    control_step_from: int
    control_step_to: int


@dataclass(frozen=True, slots=True)
class Constraints:
    injection_limits: dict[int, float] = field(default_factory=dict)
    liquid_limits: dict[int, float] = field(default_factory=dict)
    production_floors: dict[int, float] = field(default_factory=dict)
    oil_limits: dict[int, float] = field(default_factory=dict)
    watercut_limits: dict[int, float] = field(default_factory=dict)
    well_outages: tuple[WellOutage, ...] = field(default_factory=tuple)
    infrastructure: dict[str, object] = field(default_factory=dict)
    case_path: str | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class WaterSupplyPolicy:
    reinjection_fraction: float | None
    lag_steps: int
    external_water_m3_per_day: float
    fraction_defaulted: bool = False
    unlimited: bool = False

    @property
    def enabled(self) -> bool:
        return self.reinjection_fraction is not None

    def limit(self, produced_water_m3_per_day: float) -> float | None:
        if self.reinjection_fraction is None:
            return None
        return self.external_water_m3_per_day + self.reinjection_fraction * max(
            0.0, produced_water_m3_per_day
        )


@dataclass(frozen=True, slots=True)
class CompensationPolicy:
    minimum: float | None
    maximum: float | None
    enforcement: str
    scope: str

    @property
    def enabled(self) -> bool:
        return self.minimum is not None

    @property
    def hard(self) -> bool:
        return self.enforcement == "hard"


@dataclass(frozen=True, slots=True)
class FieldPressureLimits:
    floor_bar: float | None
    ceiling_bar: float | None

    @property
    def enabled(self) -> bool:
        return self.floor_bar is not None or self.ceiling_bar is not None


@dataclass(frozen=True, slots=True)
class RegionPressureLimits:
    floor_bar: float | None
    ceiling_bar: float | None

    @property
    def enabled(self) -> bool:
        return self.floor_bar is not None or self.ceiling_bar is not None


@dataclass(frozen=True, slots=True)
class BhpLimits:
    producer_min_bar: float
    injector_max_bar: float
    producer_min_defaulted: bool
    injector_max_defaulted: bool


COMPENSATION_ENFORCEMENTS = frozenset({"diagnostic", "hard"})


COMPENSATION_SCOPES = frozenset({"field", "groups", "field_and_groups"})
