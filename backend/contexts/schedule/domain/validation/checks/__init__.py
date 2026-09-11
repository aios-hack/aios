from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.contexts.schedule.domain.validation.checks.bhp_limits import (
    bhp_constraint_check,
    check_bhp_limits,
)
from backend.contexts.schedule.domain.validation.checks.compensation import (
    _check_compensation,
)
from backend.contexts.schedule.domain.validation.checks.control_modes import (
    check_control_modes,
)
from backend.contexts.schedule.domain.validation.checks.intent_versus_fact import (
    check_intent_versus_fact,
)
from backend.contexts.schedule.domain.validation.checks.interval_signs import (
    check_interval_signs,
)
from backend.contexts.schedule.domain.validation.checks.material_balance import (
    check_material_balance,
)
from backend.contexts.schedule.domain.validation.checks.outages import _check_outages
from backend.contexts.schedule.domain.validation.checks.pressure import (
    check_field_pressure,
    check_region_pressure,
)
from backend.contexts.schedule.domain.validation.checks.rate_limits import (
    _rate_limit_checks,
)
from backend.contexts.schedule.domain.validation.checks.response_axes import (
    check_response_axes,
)
from backend.contexts.schedule.domain.validation.checks.role_consistency import (
    check_role_consistency,
)
from backend.contexts.schedule.domain.validation.checks.target_ratio import (
    check_target_ratio,
)
from backend.contexts.schedule.domain.validation.checks.water_supply import (
    _check_water_supply,
)
from backend.contexts.schedule.domain.validation.checks.watercut import (
    _check_watercut_limits,
)


@dataclass(frozen=True, slots=True)
class DynamicCheck:
    name: str
    run: Callable[..., object]
    constraint_driven: bool


REGISTRY: tuple[DynamicCheck, ...] = (
    DynamicCheck("target_ratio", check_target_ratio, False),
    DynamicCheck("control_modes", check_control_modes, False),
    DynamicCheck("bhp_limits", check_bhp_limits, True),
    DynamicCheck("role_consistency", check_role_consistency, False),
    DynamicCheck("intent_versus_fact", check_intent_versus_fact, False),
    DynamicCheck("response_axes", check_response_axes, False),
    DynamicCheck("interval_signs", check_interval_signs, False),
    DynamicCheck("rate_limits", _rate_limit_checks, True),
    DynamicCheck("watercut", _check_watercut_limits, True),
    DynamicCheck("outages", _check_outages, True),
    DynamicCheck("water_supply", _check_water_supply, True),
    DynamicCheck("compensation", _check_compensation, True),
    DynamicCheck("field_pressure", check_field_pressure, True),
    DynamicCheck("region_pressure", check_region_pressure, True),
    DynamicCheck("material_balance", check_material_balance, True),
)

BY_NAME: dict[str, DynamicCheck] = {check.name: check for check in REGISTRY}


def check_named(name: str) -> DynamicCheck:
    return BY_NAME[name]


__all__ = [
    "BY_NAME",
    "REGISTRY",
    "DynamicCheck",
    "bhp_constraint_check",
    "check_bhp_limits",
    "check_control_modes",
    "check_field_pressure",
    "check_intent_versus_fact",
    "check_interval_signs",
    "check_material_balance",
    "check_named",
    "check_region_pressure",
    "check_response_axes",
    "check_role_consistency",
    "check_target_ratio",
]
