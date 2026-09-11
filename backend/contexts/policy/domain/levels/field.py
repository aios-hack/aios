from __future__ import annotations

from backend.contexts.policy.domain.hierarchy_shared import (
    FIELD_AGENT,
    WELL_LIMIT_TOLERANCE_M3_PER_DAY,
)


from backend.contexts.policy.domain.trace_types import (
    Level,
    LeveledTraceEntry,
)
from dataclasses import dataclass, replace
from typing import Mapping, Sequence
from backend.core.contracts import (
    ControlEvent,
    EventKind,
    Groups,
    Role,
    Rule,
    TraceEntry,
)
from backend.contexts.policy.domain.economics import oil_margin_rub_per_m3_liquid
from backend.contexts.policy.domain.flags import (
    RuleFlags,
)
from backend.contexts.policy.domain.rules.r1 import marginal_value_rub_per_m3
from backend.contexts.policy.domain.state import (
    PolicyState,
    RuleContext,
)


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
            raise ValueError(f"{self.group_id}: отрицательный лимит закачки")
        if self.liquid_m3_per_day is not None and self.liquid_m3_per_day < 0.0:
            raise ValueError(f"{self.group_id}: отрицательная квота жидкости")


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
                f"сумма лимитов участков {allocated} превышает лимит поля "
                f"{self.field_limit_m3_per_day}"
            )
        if self.field_liquid_limit_m3_per_day is None:
            return
        if self.field_liquid_limit_m3_per_day < 0.0:
            raise ValueError(
                f"отрицательный лимит жидкости поля: "
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
                f"сумма квот жидкости участков {liquid} превышает лимит поля "
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
        raise ValueError(f"участок {group_id} не получал лимита")


def group_demand_rub_per_m3(
    state: PolicyState, context: RuleContext, wells: Sequence[str]
) -> tuple[float, int]:
    influence = context.influence
    if influence is None:
        raise ValueError(
            "менеджер месторождения требует измеренную λ: спрос участка на "
            "воду без матрицы влияния не определён"
        )
    demand = 0.0
    counted = 0
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.INJ:
            continue
        if not observation.is_open:
            continue
        if well not in influence.injectors:
            continue
        value, _ = marginal_value_rub_per_m3(state, context, well)
        counted += 1
        if value > 0.0:
            demand += value
    return demand, counted


def group_liquid_demand_rub_per_day(
    state: PolicyState, context: RuleContext, wells: Sequence[str]
) -> tuple[float, float, int]:
    density = context.oil_density_t_per_m3
    normatives = context.normatives
    demand = 0.0
    offtake = 0.0
    counted = 0
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.PROD:
            continue
        if not observation.is_open:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        watercut = observation.watercut(density)
        margin = oil_margin_rub_per_m3_liquid(normatives, density, watercut)
        margin -= normatives.opex_liquid_rub_per_t
        offtake += observation.liquid_rate_m3_per_day
        counted += 1
        if margin > 0.0:
            demand += margin * observation.liquid_rate_m3_per_day
    return demand, offtake, counted


def _field_entry(
    state: PolicyState,
    group_id: str,
    rule: Rule,
    inputs: dict[str, float],
    decision: str,
) -> LeveledTraceEntry:
    return LeveledTraceEntry(
        level=Level.FIELD,
        agent=FIELD_AGENT,
        entry=TraceEntry(
            control_step=state.control_step,
            well=group_id,
            rule=rule,
            inputs=inputs,
            decision=decision,
        ),
    )


def allocate_field(
    state: PolicyState,
    context: RuleContext,
    flags: RuleFlags,
    field_limit_m3_per_day: float | None = None,
    field_liquid_limit_m3_per_day: float | None = None,
) -> FieldAllocation:
    if context.groups is None:
        raise ValueError(
            "менеджер месторождения раздаёт лимиты по участкам: без Groups "
            "делить нечего"
        )
    limit = (
        context.injection_budget_m3_per_day
        if field_limit_m3_per_day is None
        else field_limit_m3_per_day
    )
    if limit is None:
        raise ValueError(
            "лимит поля не задан: доступная вода — вход менеджера, а не "
            "его изобретение"
        )
    if limit < 0.0:
        raise ValueError(f"отрицательный лимит поля: {limit}")

    group_ids = tuple(sorted(context.groups.groups))
    if not group_ids:
        raise ValueError("нарезка пуста: раздавать лимиты некому")
    if not flags.is_on(Rule.R1):
        raise ValueError(
            "R1 выключено: спрос участка на воду считает правило предельной "
            "ценности, менеджер месторождения своей формулы не имеет"
        )
    liquid_limit = (
        context.liquid_budget_m3_per_day
        if field_liquid_limit_m3_per_day is None
        else field_liquid_limit_m3_per_day
    )
    if liquid_limit is not None and liquid_limit < 0.0:
        raise ValueError(f"отрицательный лимит жидкости поля: {liquid_limit}")

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


def _requested_injection(
    events: Sequence[ControlEvent], state: PolicyState, wells: Sequence[str]
) -> float:
    inside = set(wells)
    latest: dict[str, float] = {}
    for event in events:
        if event.kind is not EventKind.SET_RATE or event.value is None:
            continue
        if event.well not in inside:
            continue
        latest[event.well] = event.value
    untouched = 0.0
    for well in inside:
        if well in latest:
            continue
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.INJ:
            continue
        if not observation.is_open:
            continue
        untouched += observation.injection_rate_m3_per_day
    return sum(latest.values()) + untouched


def _untouched_injectors(
    events: Sequence[ControlEvent], state: PolicyState, wells: Sequence[str]
) -> tuple[str, ...]:
    touched = {
        event.well
        for event in events
        if event.kind is EventKind.SET_RATE and event.value is not None
    }
    return tuple(
        well
        for well in sorted(wells)
        if well not in touched
        and well in state.wells
        and state.wells[well].role is Role.INJ
        and state.wells[well].is_open
        and state.wells[well].injection_rate_m3_per_day > 0.0
    )


def _requested_liquid(
    events: Sequence[ControlEvent], state: PolicyState, wells: Sequence[str]
) -> float:
    inside = set(wells)
    latest: dict[str, float] = {}
    for event in events:
        if event.kind is not EventKind.SET_LRAT or event.value is None:
            continue
        if event.well not in inside:
            continue
        latest[event.well] = event.value
    untouched = 0.0
    for well in inside:
        if well in latest:
            continue
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.PROD:
            continue
        if not observation.is_open:
            continue
        untouched += observation.liquid_rate_m3_per_day
    return sum(latest.values()) + untouched


def _untouched_producers(
    events: Sequence[ControlEvent], state: PolicyState, wells: Sequence[str]
) -> tuple[str, ...]:
    touched = {
        event.well
        for event in events
        if event.kind is EventKind.SET_LRAT and event.value is not None
    }
    return tuple(
        well
        for well in sorted(wells)
        if well not in touched
        and well in state.wells
        and state.wells[well].role is Role.PROD
        and state.wells[well].is_open
        and state.wells[well].liquid_rate_m3_per_day > 0.0
    )


def _scale_liquid_event(event: ControlEvent, factor: float) -> ControlEvent:
    if event.kind is not EventKind.SET_LRAT or event.value is None:
        return event
    return replace(event, value=event.value * factor)


def _scale_liquid_entry(entry: TraceEntry, factor: float) -> TraceEntry:
    if entry.decision != "SET_LRAT":
        return entry
    inputs = dict(entry.inputs)
    inputs["group_liquid_limit_scale"] = factor
    if "target_rate_m3_per_day" in inputs:
        inputs["target_rate_m3_per_day"] = inputs["target_rate_m3_per_day"] * factor
    return replace(entry, inputs=inputs)


def _scale_event(event: ControlEvent, factor: float) -> ControlEvent:
    if event.kind is not EventKind.SET_RATE or event.value is None:
        return event
    return replace(event, value=event.value * factor)


def _scale_entry(entry: TraceEntry, factor: float) -> TraceEntry:
    inputs = dict(entry.inputs)
    inputs["group_limit_scale"] = factor
    if "target_rate_m3_per_day" in inputs:
        inputs["target_rate_m3_per_day"] = inputs["target_rate_m3_per_day"] * factor
    return replace(entry, inputs=inputs)


def field_limit_from_constraints(
    context: RuleContext, year: int
) -> float:
    limits: Mapping[int, float] = context.constraints.injection_limits
    if year not in limits:
        raise ValueError(
            f"лимита закачки на {year} год нет в Constraints: менеджер "
            f"месторождения не назначает доступную воду сам"
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
