from __future__ import annotations

from backend.contexts.policy.domain.hierarchy_shared import (
    FIELD_AGENT,
    PRODUCTION_FLOOR_MET,
    PRODUCTION_FLOOR_NOT_SET,
    PRODUCTION_FLOOR_UNREACHABLE,
    WELL_LIMIT_TOLERANCE_M3_PER_DAY,
    group_of,
    observations_by_group,
    restrict,
    wells_without_group,
)


from backend.contexts.policy.domain.levels.group import (
    GroupDecision,
)
from backend.contexts.policy.domain.levels.field import (
    GroupLimit,
    allocate_field,
    field_limit_from_constraints,
    group_demand_rub_per_m3,
    group_liquid_demand_rub_per_day,
)
from backend.contexts.policy.domain.levels.group import (
    decide_group,
    rules_for_group,
)
from backend.contexts.policy.domain.levels.well import (
    execute_well,
)
from backend.contexts.policy.domain.production_floor import (
    ProductionFloorCheck,
    check_production_floor,
    predicted_oil_t_per_day,
)
from backend.contexts.policy.domain.trace_types import (
    Level,
    LeveledTraceEntry,
)
from backend.contexts.policy.domain.watercut_shutins import (
    binding_watercut_limit,
    watercut_cap_shutins,
)

from backend.contexts.policy.domain.levels.field import (
    FieldAllocation,
)


from backend.contexts.policy.domain.trace_types import (
    HierarchyTrace,
)

from dataclasses import (
    dataclass,
)
from typing import (
    Sequence,
)

from backend.core.contracts import (
    ControlEvent,
    EventKind,
    Groups,
)

from backend.contexts.policy.domain.state import (
    PolicyState,
    WellObservation,
)


@dataclass(frozen=True, slots=True)
class HierarchyResult:
    allocation: FieldAllocation
    group_decisions: tuple[GroupDecision, ...]
    decisions: tuple[ControlEvent, ...]
    trace: HierarchyTrace

    def injected_m3_per_day(self) -> float:
        return sum(
            event.value
            for event in self.decisions
            if event.kind is EventKind.SET_RATE and event.value is not None
        )




__all__ = [
    "FIELD_AGENT",
    "FieldAllocation",
    "GroupDecision",
    "GroupLimit",
    "HierarchyResult",
    "HierarchyTrace",
    "Level",
    "LeveledTraceEntry",
    "PRODUCTION_FLOOR_MET",
    "PRODUCTION_FLOOR_NOT_SET",
    "PRODUCTION_FLOOR_UNREACHABLE",
    "ProductionFloorCheck",
    "WELL_LIMIT_TOLERANCE_M3_PER_DAY",
    "allocate_field",
    "binding_watercut_limit",
    "check_production_floor",
    "decide_group",
    "execute_well",
    "field_limit_from_constraints",
    "group_demand_rub_per_m3",
    "group_liquid_demand_rub_per_day",
    "group_of",
    "observations_by_group",
    "predicted_oil_t_per_day",
    "restrict",
    "rules_for_group",
    "watercut_cap_shutins",
    "wells_without_group",
]
