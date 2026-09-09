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

SOURCE_SUFFIX = "_source"

SOURCE_ORGANIZER = "organizer"
SOURCE_DIAGNOSTIC = "diagnostic"
SOURCE_ASSUMPTION = "assumption"

CONSTRAINT_SOURCES: frozenset[str] = frozenset(
    {SOURCE_ORGANIZER, SOURCE_DIAGNOSTIC, SOURCE_ASSUMPTION}
)

SOURCE_LABELS: dict[str, str] = {
    SOURCE_ORGANIZER: "условие организаторов",
    SOURCE_DIAGNOSTIC: "диагностический ориентир",
    SOURCE_ASSUMPTION: "допущение нашей стороны",
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
    watercut_limits: dict[int, float] = field(default_factory=dict)
    well_outages: tuple[WellOutage, ...] = field(default_factory=tuple)
    infrastructure: dict[str, object] = field(default_factory=dict)
    case_path: str | None = None


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
class BhpLimits:
    producer_min_bar: float
    injector_max_bar: float
    producer_min_defaulted: bool
    injector_max_defaulted: bool


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


def constraint_source(constraints: Constraints, key: str) -> str | None:
    if key not in SOURCED_INFRASTRUCTURE_KEYS:
        raise ValueError(
            f"infrastructure.{key}: источник объявляется только для параметров "
            f"{', '.join(SOURCED_INFRASTRUCTURE_KEYS)}"
        )
    raw = constraints.infrastructure.get(source_key(key))
    if raw is None:
        if key in constraints.infrastructure:
            return None
        return DEFAULT_SOURCES.get(key)
    if not isinstance(raw, str) or raw not in CONSTRAINT_SOURCES:
        raise ValueError(
            f"infrastructure.{source_key(key)}: ожидается одно из "
            f"{sorted(CONSTRAINT_SOURCES)}, получено {raw!r}"
        )
    return raw


def source_label(source: str | None) -> str:
    if source is None:
        return "источник не объявлен"
    return SOURCE_LABELS.get(source, source)


def limit_origin(constraints: Constraints, key: str) -> str:
    source = constraint_source(constraints, key)
    where = constraints.case_path if constraints.case_path else "кейс не из файла"
    if source is None:
        return f"источник не объявлен, кейс {where}"
    return f"источник {source} ({source_label(source)}), кейс {where}"


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


def bhp_limits(constraints: Constraints) -> BhpLimits:
    source = constraints.infrastructure
    producer_defaulted = BHP_PRODUCER_MIN_BAR not in source
    injector_defaulted = BHP_INJECTOR_MAX_BAR not in source
    producer_min = _finite_number(
        source, BHP_PRODUCER_MIN_BAR, DEFAULT_BHP_PRODUCER_MIN_BAR
    )
    injector_max = _finite_number(
        source, BHP_INJECTOR_MAX_BAR, DEFAULT_BHP_INJECTOR_MAX_BAR
    )
    if producer_min <= 0.0:
        raise ValueError(
            f"infrastructure.{BHP_PRODUCER_MIN_BAR}: нижний предел забойного "
            f"давления добывающей должен быть положительным, получено {producer_min}"
        )
    if injector_max <= 0.0:
        raise ValueError(
            f"infrastructure.{BHP_INJECTOR_MAX_BAR}: верхний предел забойного "
            "давления нагнетательной должен быть положительным, получено "
            f"{injector_max}"
        )
    if injector_max <= producer_min:
        raise ValueError(
            f"infrastructure.{BHP_INJECTOR_MAX_BAR}: верхний предел "
            f"{injector_max} бар не выше нижнего {producer_min} бар: "
            "коридор забойного давления пуст"
        )
    return BhpLimits(
        producer_min_bar=producer_min,
        injector_max_bar=injector_max,
        producer_min_defaulted=producer_defaulted,
        injector_max_defaulted=injector_defaulted,
    )


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
