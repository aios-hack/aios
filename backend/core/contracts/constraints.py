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

DEFAULT_WATER_SAFETY_FACTOR = 1.0

COMPENSATION_ENFORCEMENTS = frozenset({"diagnostic", "hard"})
COMPENSATION_SCOPES = frozenset({"field", "groups", "field_and_groups"})


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
    watercut_limits: dict[int, float] = field(default_factory=dict)
    well_outages: tuple[WellOutage, ...] = field(default_factory=tuple)
    infrastructure: dict[str, object] = field(default_factory=dict)


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


def _finite_number(source: dict[str, object], key: str, default: float) -> float:
    raw: Any = source.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"infrastructure.{key}: ожидается число")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"infrastructure.{key}: ожидается конечное число")
    return value


def _unlimited_flag(source: dict[str, object]) -> bool:
    raw = source.get(WATER_SUPPLY_UNLIMITED, False)
    if not isinstance(raw, bool):
        raise ValueError(
            f"infrastructure.{WATER_SUPPLY_UNLIMITED}: ожидается true или false"
        )
    return raw


def water_supply_policy(constraints: Constraints) -> WaterSupplyPolicy:
    source = constraints.infrastructure
    unlimited = _unlimited_flag(source)
    has_fraction = WATER_REINJECTION_FRACTION in source
    has_lag = WATER_REINJECTION_LAG_STEPS in source
    has_external = EXTERNAL_WATER_M3_PER_DAY in source
    if unlimited and (has_fraction or has_lag or has_external):
        raise ValueError(
            f"infrastructure.{WATER_SUPPLY_UNLIMITED}: источник воды объявлен "
            "неограниченным, поэтому вместе с ним нельзя задавать "
            f"{WATER_REINJECTION_FRACTION}, {WATER_REINJECTION_LAG_STEPS} или "
            f"{EXTERNAL_WATER_M3_PER_DAY}"
        )
    if unlimited:
        return WaterSupplyPolicy(None, 0, 0.0, False, True)
    if not (has_fraction or has_lag or has_external):
        return WaterSupplyPolicy(None, 0, 0.0, False, False)
    fraction_defaulted = not has_fraction
    fraction = _finite_number(source, WATER_REINJECTION_FRACTION, 1.0)
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(
            f"infrastructure.{WATER_REINJECTION_FRACTION}: доля должна быть "
            f"в диапазоне 0..1, получено {fraction}"
        )
    raw_lag = source.get(WATER_REINJECTION_LAG_STEPS, 0)
    if isinstance(raw_lag, bool) or not isinstance(raw_lag, int) or raw_lag < 0:
        raise ValueError(
            f"infrastructure.{WATER_REINJECTION_LAG_STEPS}: ожидается целое >= 0"
        )
    external = _finite_number(source, EXTERNAL_WATER_M3_PER_DAY, 0.0)
    if external < 0.0:
        raise ValueError(
            f"infrastructure.{EXTERNAL_WATER_M3_PER_DAY}: внешний приток "
            "не может быть отрицательным"
        )
    return WaterSupplyPolicy(
        fraction, raw_lag, external, fraction_defaulted, False
    )


def water_safety_factor(constraints: Constraints) -> float:
    source = constraints.infrastructure
    if WATER_SAFETY_FACTOR not in source:
        return DEFAULT_WATER_SAFETY_FACTOR
    value = _finite_number(source, WATER_SAFETY_FACTOR, DEFAULT_WATER_SAFETY_FACTOR)
    if not 0.0 < value <= 1.0:
        raise ValueError(
            f"infrastructure.{WATER_SAFETY_FACTOR}: запас должен лежать в "
            f"диапазоне (0, 1], получено {value}"
        )
    return value


def compensation_policy(constraints: Constraints) -> CompensationPolicy:
    source = constraints.infrastructure
    has_min = COMPENSATION_MIN in source
    has_max = COMPENSATION_MAX in source
    if has_min != has_max:
        missing = COMPENSATION_MAX if has_min else COMPENSATION_MIN
        raise ValueError(
            f"infrastructure.{missing} обязателен: коридор компенсации "
            "задаётся двумя границами"
        )
    if not has_min:
        return CompensationPolicy(None, None, "diagnostic", "field_and_groups")

    minimum = _finite_number(source, COMPENSATION_MIN, 0.0)
    maximum = _finite_number(source, COMPENSATION_MAX, 0.0)
    if minimum < 0.0:
        raise ValueError(f"infrastructure.{COMPENSATION_MIN}: значение < 0")
    if maximum < minimum:
        raise ValueError(f"коридор компенсации пуст: {minimum}..{maximum}")

    enforcement = source.get(COMPENSATION_ENFORCEMENT, "diagnostic")
    if enforcement not in COMPENSATION_ENFORCEMENTS:
        raise ValueError(
            f"infrastructure.{COMPENSATION_ENFORCEMENT}: ожидается одно из "
            f"{sorted(COMPENSATION_ENFORCEMENTS)}, получено {enforcement!r}"
        )
    scope = source.get(COMPENSATION_SCOPE, "field_and_groups")
    if scope not in COMPENSATION_SCOPES:
        raise ValueError(
            f"infrastructure.{COMPENSATION_SCOPE}: ожидается одно из "
            f"{sorted(COMPENSATION_SCOPES)}, получено {scope!r}"
        )
    return CompensationPolicy(minimum, maximum, str(enforcement), str(scope))
