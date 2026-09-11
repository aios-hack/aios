from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from backend.contexts.policy.domain.flags import RuleFlags
from backend.contexts.policy.domain.hierarchy_shared import (
    FIELD_AGENT,
    WELL_LIMIT_TOLERANCE_M3_PER_DAY,
)
from backend.contexts.policy.domain.levels.field_demand import (
    _field_entry,
    group_demand_rub_per_m3,
    group_liquid_demand_rub_per_day,
)
from backend.contexts.policy.domain.levels.field_rescale import (
    _requested_injection,
    _requested_liquid,
    _scale_entry,
    _scale_event,
    _scale_liquid_entry,
    _scale_liquid_event,
    _untouched_injectors,
    _untouched_producers,
)
from backend.contexts.policy.domain.policy import Rule, TraceEntry
from backend.contexts.policy.domain.state import PolicyState, RuleContext
from backend.contexts.policy.domain.trace_types import Level, LeveledTraceEntry
from backend.contexts.schedule.domain.schedule import ControlEvent, EventKind, Role


@dataclass(frozen=True, slots=True)
class GroupLimit:
    group_id: str
    injection_m3_per_day: float
    share_of_field: float
    demand_rub_per_m3: float
    liquid_m3_per_day: float | None = None
    liquid_share_of_field: float | None = None
    liquid_demand_rub_per_day: float | None = None

    def __post_init__(self) -> None:
        if self.injection_m3_per_day < 0.0:
            raise ValueError(f"{self.group_id}: negative injection limit")
        if self.liquid_m3_per_day is not None and self.liquid_m3_per_day < 0.0:
            raise ValueError(f"{self.group_id}: negative liquid quota")


@dataclass(frozen=True, slots=True)
class FieldAllocation:
    field_limit_m3_per_day: float
    limits: tuple[GroupLimit, ...]
    trace: tuple[LeveledTraceEntry, ...]
    field_liquid_limit_m3_per_day: float | None = None

    def __post_init__(self) -> None:
        allocated = sum(limit.injection_m3_per_day for limit in self.limits)
        if allocated > self.field_limit_m3_per_day + WELL_LIMIT_TOLERANCE_M3_PER_DAY:
            raise ValueError(
                f"the sum of group limits {allocated} exceeds the field limit "
                f"{self.field_limit_m3_per_day}"
            )
        if self.field_liquid_limit_m3_per_day is None:
            return
        if self.field_liquid_limit_m3_per_day < 0.0:
            raise ValueError(
                f"negative field liquid limit: "
                f"{self.field_liquid_limit_m3_per_day}"
            )
        liquid = sum(
            limit.liquid_m3_per_day or 0.0 for limit in self.limits
        )
        if (
            liquid
            > self.field_liquid_limit_m3_per_day + WELL_LIMIT_TOLERANCE_M3_PER_DAY
        ):
            raise ValueError(
                f"the sum of group liquid quotas {liquid} exceeds the field limit "
                f"{self.field_liquid_limit_m3_per_day}"
            )

    def allocated_m3_per_day(self) -> float:
        return sum(limit.injection_m3_per_day for limit in self.limits)

    def allocated_liquid_m3_per_day(self) -> float:
        return sum(limit.liquid_m3_per_day or 0.0 for limit in self.limits)

    def of(self, group_id: str) -> GroupLimit:
        for limit in self.limits:
            if limit.group_id == group_id:
                return limit
        raise ValueError(f"group {group_id} received no limit")


def allocate_field(
    state: PolicyState,
    context: RuleContext,
    flags: RuleFlags,
    field_limit_m3_per_day: float | None = None,
    field_liquid_limit_m3_per_day: float | None = None,
) -> FieldAllocation:
    if context.groups is None:
        raise ValueError(
            "the field manager hands out limits across groups: without Groups "
            "there is nothing to split"
        )
    limit = (
        context.injection_budget_m3_per_day
        if field_limit_m3_per_day is None
        else field_limit_m3_per_day
    )
    if limit is None:
        raise ValueError(
            "the field limit is not set: the available water is an input to the manager, not "
            "an invention of his"
        )
    if limit < 0.0:
        raise ValueError(f"negative field limit: {limit}")

    group_ids = tuple(sorted(context.groups.groups))
    if not group_ids:
        raise ValueError("the grouping is empty: there is nobody to hand limits out to")
    if not flags.is_on(Rule.R1):
        raise ValueError(
            "R1 is off: the group water demand is computed by the marginal-value "
            "rule, and the field manager has no formula of its own"
        )
    liquid_limit = (
        context.liquid_budget_m3_per_day
        if field_liquid_limit_m3_per_day is None
        else field_liquid_limit_m3_per_day
    )
    if liquid_limit is not None and liquid_limit < 0.0:
        raise ValueError(f"negative field liquid limit: {liquid_limit}")

    demands: dict[str, float] = {}
    counted: dict[str, int] = {}
    liquid_demands: dict[str, float] = {}
    liquid_offtake: dict[str, float] = {}
    producers_counted: dict[str, int] = {}
    for group_id in group_ids:
        demand, injectors = group_demand_rub_per_m3(
            state, context, context.groups.groups[group_id]
        )
        demands[group_id] = demand
        counted[group_id] = injectors
        if liquid_limit is not None:
            value, offtake, producers = group_liquid_demand_rub_per_day(
                state, context, context.groups.groups[group_id]
            )
            liquid_demands[group_id] = value
            liquid_offtake[group_id] = offtake
            producers_counted[group_id] = producers
    total_demand = sum(demands.values())
    total_liquid_demand = sum(liquid_demands.values())
    total_offtake = sum(liquid_offtake.values())

    limits: list[GroupLimit] = []
    trace: list[LeveledTraceEntry] = []
    for group_id in group_ids:
        demand = demands[group_id]
        if total_demand > 0.0:
            share = demand / total_demand
        else:
            share = 0.0
        allocated = limit * share
        liquid_share: float | None = None
        liquid_quota: float | None = None
        if liquid_limit is not None:
            if total_liquid_demand > 0.0:
                liquid_share = liquid_demands[group_id] / total_liquid_demand
            elif total_offtake > 0.0:
                liquid_share = liquid_offtake[group_id] / total_offtake
            else:
                liquid_share = 0.0
            liquid_quota = liquid_limit * liquid_share
        limits.append(
            GroupLimit(
                group_id=group_id,
                injection_m3_per_day=allocated,
                share_of_field=share,
                demand_rub_per_m3=demand,
                liquid_m3_per_day=liquid_quota,
                liquid_share_of_field=liquid_share,
                liquid_demand_rub_per_day=(
                    liquid_demands[group_id] if liquid_limit is not None else None
                ),
            )
        )
        trace.append(
            _field_entry(
                state,
                group_id,
                Rule.R1,
                {
                    "field_injection_limit_m3_per_day": limit,
                    "group_demand_rub_per_m3": demand,
                    "field_demand_rub_per_m3": total_demand,
                    "share_of_field": share,
                    "group_limit_m3_per_day": allocated,
                    "injectors_in_group": float(counted[group_id]),
                    "groups_in_field": float(len(group_ids)),
                },
                "SET_GROUP_LIMIT",
            )
        )
        if liquid_limit is None or not flags.is_on(Rule.R2):
            continue
        assert liquid_quota is not None and liquid_share is not None
        trace.append(
            _field_entry(
                state,
                group_id,
                Rule.R2,
                {
                    "field_liquid_limit_m3_per_day": liquid_limit,
                    "group_liquid_demand_rub_per_day": liquid_demands[group_id],
                    "field_liquid_demand_rub_per_day": total_liquid_demand,
                    "group_liquid_rate_m3_per_day": liquid_offtake[group_id],
                    "field_liquid_rate_m3_per_day": total_offtake,
                    "liquid_share_of_field": liquid_share,
                    "group_liquid_limit_m3_per_day": liquid_quota,
                    "producers_in_group": float(producers_counted[group_id]),
                    "groups_in_field": float(len(group_ids)),
                },
                "SET_GROUP_LIQUID_LIMIT",
            )
        )
    return FieldAllocation(
        field_limit_m3_per_day=limit,
        limits=tuple(limits),
        trace=tuple(trace),
        field_liquid_limit_m3_per_day=liquid_limit,
    )


def field_limit_from_constraints(
    context: RuleContext, year: int
) -> float:
    limits: Mapping[int, float] = context.constraints.injection_limits
    if year not in limits:
        raise ValueError(
            f"the injection limit for the year {year} is absent from Constraints: the field "
            f"manager does not assign the available water itself"
        )
    return limits[year]


__all__ = [
    "FieldAllocation",
    "GroupLimit",
    "allocate_field",
    "field_limit_from_constraints",
    "group_demand_rub_per_m3",
    "group_liquid_demand_rub_per_day",
]
