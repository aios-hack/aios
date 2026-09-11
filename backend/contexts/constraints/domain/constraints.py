from __future__ import annotations

import math
from typing import Any

from backend.contexts.constraints.domain.constraint_types import (
    BHP_INJECTOR_MAX_BAR,
    BHP_PRODUCER_MIN_BAR,
    BLOCKING_INFRASTRUCTURE_KEYS,
    BhpLimits,
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_ENFORCEMENTS,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    COMPENSATION_SCOPE,
    COMPENSATION_SCOPES,
    CONSTRAINT_SOURCES,
    CompensationPolicy,
    Constraints,
    DEFAULT_BHP_INJECTOR_MAX_BAR,
    DEFAULT_BHP_PRODUCER_MIN_BAR,
    DEFAULT_SOURCES,
    DEFAULT_WATER_SAFETY_FACTOR,
    DIAGNOSTIC_INFRASTRUCTURE_KEYS,
    EXTERNAL_WATER_M3_PER_DAY,
    FieldPressureLimits,
    PRESSURE_CEILING_BAR,
    PRESSURE_FLOOR_BAR,
    REGION_PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    RegionPressureLimits,
    SOURCE_ASSUMPTION,
    SOURCE_DIAGNOSTIC,
    SOURCE_LABELS,
    SOURCE_ORGANIZER,
    SOURCE_SUFFIX,
    SOURCED_INFRASTRUCTURE_KEYS,
    WATER_REINJECTION_FRACTION,
    WATER_REINJECTION_LAG_STEPS,
    WATER_SAFETY_FACTOR,
    WATER_SUPPLY_UNLIMITED,
    WaterSupplyPolicy,
    WellOutage,
    source_key,
)


def _finite_number(source: dict[str, object], key: str, default: float) -> float:
    raw: Any = source.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"infrastructure.{key}: a number is expected")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"infrastructure.{key}: a finite number is expected")
    return value


def _unlimited_flag(source: dict[str, object]) -> bool:
    raw = source.get(WATER_SUPPLY_UNLIMITED, False)
    if not isinstance(raw, bool):
        raise ValueError(
            f"infrastructure.{WATER_SUPPLY_UNLIMITED}: true or false is expected"
        )
    return raw


def constraint_source(constraints: Constraints, key: str) -> str | None:
    if key not in SOURCED_INFRASTRUCTURE_KEYS:
        raise ValueError(
            f"infrastructure.{key}: a source is declared only for the parameters "
            f"{', '.join(SOURCED_INFRASTRUCTURE_KEYS)}"
        )
    raw = constraints.infrastructure.get(source_key(key))
    if raw is None:
        if key in constraints.infrastructure:
            return None
        return DEFAULT_SOURCES.get(key)
    if not isinstance(raw, str) or raw not in CONSTRAINT_SOURCES:
        raise ValueError(
            f"infrastructure.{source_key(key)}: one of "
            f"{sorted(CONSTRAINT_SOURCES)} is expected, got {raw!r}"
        )
    return raw


def source_label(source: str | None) -> str:
    if source is None:
        return "source not declared"
    return SOURCE_LABELS.get(source, source)


def limit_origin(constraints: Constraints, key: str) -> str:
    source = constraint_source(constraints, key)
    where = constraints.case_path if constraints.case_path else "case not from a file"
    if source is None:
        return f"source not declared, case {where}"
    return f"source {source} ({source_label(source)}), case {where}"


def water_supply_policy(constraints: Constraints) -> WaterSupplyPolicy:
    source = constraints.infrastructure
    unlimited = _unlimited_flag(source)
    has_fraction = WATER_REINJECTION_FRACTION in source
    has_lag = WATER_REINJECTION_LAG_STEPS in source
    has_external = EXTERNAL_WATER_M3_PER_DAY in source
    if unlimited and (has_fraction or has_lag or has_external):
        raise ValueError(
            f"infrastructure.{WATER_SUPPLY_UNLIMITED}: the water source is declared "
            "unlimited, so it cannot be given together with "
            f"{WATER_REINJECTION_FRACTION}, {WATER_REINJECTION_LAG_STEPS} or "
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
            f"infrastructure.{WATER_REINJECTION_FRACTION}: the fraction must lie "
            f"in the range 0..1, got {fraction}"
        )
    raw_lag = source.get(WATER_REINJECTION_LAG_STEPS, 0)
    if isinstance(raw_lag, bool) or not isinstance(raw_lag, int) or raw_lag < 0:
        raise ValueError(
            f"infrastructure.{WATER_REINJECTION_LAG_STEPS}: an integer >= 0 is expected"
        )
    external = _finite_number(source, EXTERNAL_WATER_M3_PER_DAY, 0.0)
    if external < 0.0:
        raise ValueError(
            f"infrastructure.{EXTERNAL_WATER_M3_PER_DAY}: the external inflow "
            "cannot be negative"
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
            f"infrastructure.{WATER_SAFETY_FACTOR}: the safety factor must lie in "
            f"the range (0, 1], got {value}"
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
            f"infrastructure.{BHP_PRODUCER_MIN_BAR}: the lower bottomhole pressure "
            f"limit of a producer must be positive, got {producer_min}"
        )
    if injector_max <= 0.0:
        raise ValueError(
            f"infrastructure.{BHP_INJECTOR_MAX_BAR}: the upper bottomhole pressure "
            "limit of an injector must be positive, got "
            f"{injector_max}"
        )
    if injector_max <= producer_min:
        raise ValueError(
            f"infrastructure.{BHP_INJECTOR_MAX_BAR}: the upper limit "
            f"{injector_max} bar is not above the lower {producer_min} bar: "
            "the bottomhole pressure corridor is empty"
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
            f"infrastructure.{missing} is mandatory: the compensation corridor "
            "is given by two bounds"
        )
    if not has_min:
        return CompensationPolicy(None, None, "diagnostic", "field_and_groups")

    minimum = _finite_number(source, COMPENSATION_MIN, 0.0)
    maximum = _finite_number(source, COMPENSATION_MAX, 0.0)
    if minimum < 0.0:
        raise ValueError(f"infrastructure.{COMPENSATION_MIN}: the value is < 0")
    if maximum < minimum:
        raise ValueError(f"the compensation corridor is empty: {minimum}..{maximum}")

    enforcement = source.get(COMPENSATION_ENFORCEMENT, "diagnostic")
    if enforcement not in COMPENSATION_ENFORCEMENTS:
        raise ValueError(
            f"infrastructure.{COMPENSATION_ENFORCEMENT}: one of "
            f"{sorted(COMPENSATION_ENFORCEMENTS)} is expected, got {enforcement!r}"
        )
    scope = source.get(COMPENSATION_SCOPE, "field_and_groups")
    if scope not in COMPENSATION_SCOPES:
        raise ValueError(
            f"infrastructure.{COMPENSATION_SCOPE}: one of "
            f"{sorted(COMPENSATION_SCOPES)} is expected, got {scope!r}"
        )
    return CompensationPolicy(minimum, maximum, str(enforcement), str(scope))


def field_pressure_limits(constraints: Constraints) -> FieldPressureLimits:
    source = constraints.infrastructure
    has_floor = PRESSURE_FLOOR_BAR in source
    has_ceiling = PRESSURE_CEILING_BAR in source
    if not (has_floor or has_ceiling):
        return FieldPressureLimits(None, None)
    floor = (
        _finite_number(source, PRESSURE_FLOOR_BAR, 0.0) if has_floor else None
    )
    ceiling = (
        _finite_number(source, PRESSURE_CEILING_BAR, 0.0) if has_ceiling else None
    )
    if floor is not None and floor <= 0.0:
        raise ValueError(
            f"infrastructure.{PRESSURE_FLOOR_BAR}: the reservoir pressure floor "
            f"must be positive, got {floor}"
        )
    if ceiling is not None and ceiling <= 0.0:
        raise ValueError(
            f"infrastructure.{PRESSURE_CEILING_BAR}: the reservoir pressure "
            f"ceiling must be positive, got {ceiling}"
        )
    if floor is not None and ceiling is not None and ceiling <= floor:
        raise ValueError(
            f"infrastructure.{PRESSURE_CEILING_BAR}: the ceiling {ceiling} bar is "
            f"not above the floor {floor} bar: the reservoir pressure corridor is empty"
        )
    return FieldPressureLimits(floor, ceiling)


def region_pressure_limits(constraints: Constraints) -> RegionPressureLimits:
    source = constraints.infrastructure
    has_floor = REGION_PRESSURE_FLOOR_BAR in source
    has_ceiling = REGION_PRESSURE_CEILING_BAR in source
    if not (has_floor or has_ceiling):
        return RegionPressureLimits(None, None)
    floor = (
        _finite_number(source, REGION_PRESSURE_FLOOR_BAR, 0.0)
        if has_floor
        else None
    )
    ceiling = (
        _finite_number(source, REGION_PRESSURE_CEILING_BAR, 0.0)
        if has_ceiling
        else None
    )
    if floor is not None and floor <= 0.0:
        raise ValueError(
            f"infrastructure.{REGION_PRESSURE_FLOOR_BAR}: the regional reservoir "
            f"pressure floor must be positive, got {floor}"
        )
    if ceiling is not None and ceiling <= 0.0:
        raise ValueError(
            f"infrastructure.{REGION_PRESSURE_CEILING_BAR}: the regional reservoir "
            "pressure ceiling must be positive, "
            f"got {ceiling}"
        )
    if floor is not None and ceiling is not None and ceiling <= floor:
        raise ValueError(
            f"infrastructure.{REGION_PRESSURE_CEILING_BAR}: the ceiling {ceiling} "
            f"bar is not above the floor {floor} bar: the regional reservoir "
            "pressure corridor is empty"
        )
    return RegionPressureLimits(floor, ceiling)
