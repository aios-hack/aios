from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping, Sequence

from backend.core.contracts import (
    MAX_LRAT_M3_PER_DAY,
    ControlEvent,
    EventKind,
    Groups,
    Role,
    Rule,
    Theta,
    TraceEntry,
)

from backend.domain.policy.economics import oil_margin_rub_per_m3_liquid
from backend.domain.policy.flags import (
    IMPLEMENTED_RULES,
    WATERCUT_CAP_FEATURE,
    RuleFlags,
)
from backend.domain.policy.rules import apply_rule, superseded
from backend.domain.policy.rules.base import RuleOutcome
from backend.domain.policy.rules.r1 import marginal_value_rub_per_m3
from backend.domain.policy.state import PolicyState, RuleContext, WellObservation
from backend.domain.policy.trace import RunTrace

FIELD_AGENT = "field"
WELL_LIMIT_TOLERANCE_M3_PER_DAY = 1e-9


class Level(Enum):
    FIELD = "FIELD"
    GROUP = "GROUP"
    WELL = "WELL"


@dataclass(frozen=True, slots=True)
class LeveledTraceEntry:
    level: Level
    agent: str
    entry: TraceEntry

    def __post_init__(self) -> None:
        if not self.agent:
            raise ValueError("запись Trace без имени агента: уровень не восстановим")
        if not self.entry.inputs:
            raise ValueError(
                f"{self.level.value}/{self.agent}: запись Trace без чисел входа"
            )


@dataclass(frozen=True, slots=True)
class HierarchyTrace:
    entries: tuple[LeveledTraceEntry, ...]
    flags: RuleFlags

    def __post_init__(self) -> None:
        for leveled in self.entries:
            if not self.flags.is_on(leveled.entry.rule):
                raise ValueError(
                    f"{leveled.entry.rule.value} выключено флагом, но оставило "
                    f"запись уровня {leveled.level.value} у агента "
                    f"{leveled.agent}"
                )

    def __len__(self) -> int:
        return len(self.entries)

    def by_level(self, level: Level) -> tuple[LeveledTraceEntry, ...]:
        return tuple(e for e in self.entries if e.level is level)

    def by_agent(self, agent: str) -> tuple[LeveledTraceEntry, ...]:
        return tuple(e for e in self.entries if e.agent == agent)

    def levels_present(self) -> tuple[Level, ...]:
        seen = {e.level for e in self.entries}
        return tuple(level for level in Level if level in seen)

    def count_by_level(self) -> dict[Level, int]:
        counted = {level: 0 for level in Level}
        for leveled in self.entries:
            counted[leveled.level] += 1
        return counted

    def as_run_trace(self) -> RunTrace:
        return RunTrace(
            entries=tuple(e.entry for e in self.entries), flags=self.flags
        )

    def by_rule(self, rule: Rule) -> tuple[LeveledTraceEntry, ...]:
        return tuple(e for e in self.entries if e.entry.rule is rule)

    def levels_of(self, well: str) -> tuple[Level, ...]:
        seen = {e.level for e in self.entries if e.entry.well == well}
        return tuple(level for level in Level if level in seen)


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


@dataclass(frozen=True, slots=True)
class GroupDecision:
    group_id: str
    limit: GroupLimit
    decisions: tuple[ControlEvent, ...]
    rule_by_decision: tuple[Rule, ...]
    trace: tuple[LeveledTraceEntry, ...]
    requested_injection_m3_per_day: float
    requested_liquid_m3_per_day: float | None = None

    def __post_init__(self) -> None:
        if (
            self.requested_injection_m3_per_day
            > self.limit.injection_m3_per_day + WELL_LIMIT_TOLERANCE_M3_PER_DAY
        ):
            raise ValueError(
                f"участок {self.group_id} запросил "
                f"{self.requested_injection_m3_per_day} при лимите "
                f"{self.limit.injection_m3_per_day}"
            )
        if self.requested_liquid_m3_per_day is None:
            return
        if self.limit.liquid_m3_per_day is None:
            raise ValueError(
                f"участок {self.group_id} отчитался об отборе жидкости "
                f"{self.requested_liquid_m3_per_day} м³/сут, не получив квоты"
            )
        if (
            self.requested_liquid_m3_per_day
            > self.limit.liquid_m3_per_day + WELL_LIMIT_TOLERANCE_M3_PER_DAY
        ):
            raise ValueError(
                f"участок {self.group_id} запросил жидкости "
                f"{self.requested_liquid_m3_per_day} при квоте "
                f"{self.limit.liquid_m3_per_day}"
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


def group_of(groups: Groups, well: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            group_id
            for group_id, wells in groups.groups.items()
            if well in wells
        )
    )


def restrict(state: PolicyState, wells: Sequence[str]) -> PolicyState:
    inside = {well: state.wells[well] for well in wells if well in state.wells}
    return PolicyState(control_step=state.control_step, wells=inside)


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


PRODUCTION_FLOOR_UNREACHABLE = "PRODUCTION_FLOOR_UNREACHABLE"
PRODUCTION_FLOOR_NOT_SET = "PRODUCTION_FLOOR_NOT_SET"
PRODUCTION_FLOOR_MET = "PRODUCTION_FLOOR_MET"


@dataclass(frozen=True, slots=True)
class ProductionFloorCheck:
    year: int | None
    floor_t_per_day: float | None
    predicted_t_per_day: float | None
    status: str

    @property
    def attempted(self) -> bool:
        return self.status != PRODUCTION_FLOOR_NOT_SET

    @property
    def unreachable(self) -> bool:
        return self.status == PRODUCTION_FLOOR_UNREACHABLE

    def as_entry(self, control_step: int, agent: str) -> TraceEntry:
        if self.floor_t_per_day is None or self.predicted_t_per_day is None:
            raise ValueError(
                "пол добычи не измерялся: записи в трассу для него нет"
            )
        return TraceEntry(
            control_step=control_step,
            well=agent,
            rule=Rule.R0,
            inputs={
                "production_floor_t_per_day": self.floor_t_per_day,
                "predicted_oil_t_per_day": self.predicted_t_per_day,
                "production_floor_shortfall_t_per_day": (
                    self.floor_t_per_day - self.predicted_t_per_day
                ),
                "production_floor_year": float(self.year or 0),
            },
            decision=self.status,
        )


def predicted_oil_t_per_day(
    state: PolicyState,
    events: Sequence[ControlEvent],
    context: RuleContext,
    wells: Sequence[str],
) -> float:
    density = context.oil_density_t_per_m3
    total = 0.0
    shut = _shut_wells(events)
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.PROD:
            continue
        if not observation.is_open or well in shut:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        liquid = _effective_liquid(events, state, well)
        share = liquid / observation.liquid_rate_m3_per_day
        total += observation.oil_rate_t_per_day * share
    return total


def check_production_floor(
    state: PolicyState,
    context: RuleContext,
    events: Sequence[ControlEvent],
    wells: Sequence[str],
    year: int | None,
) -> ProductionFloorCheck:
    floors = context.constraints.production_floors
    if not floors:
        return ProductionFloorCheck(
            year=year,
            floor_t_per_day=None,
            predicted_t_per_day=None,
            status=PRODUCTION_FLOOR_NOT_SET,
        )
    if year is None:
        floor = max(float(value) for value in floors.values())
    else:
        declared = floors.get(year)
        if declared is None:
            return ProductionFloorCheck(
                year=year,
                floor_t_per_day=None,
                predicted_t_per_day=None,
                status=PRODUCTION_FLOOR_NOT_SET,
            )
        floor = float(declared)
    predicted = predicted_oil_t_per_day(state, events, context, wells)
    status = (
        PRODUCTION_FLOOR_UNREACHABLE if predicted < floor else PRODUCTION_FLOOR_MET
    )
    return ProductionFloorCheck(
        year=year,
        floor_t_per_day=floor,
        predicted_t_per_day=predicted,
        status=status,
    )


def binding_watercut_limit(context: RuleContext) -> float | None:
    limits = context.constraints.watercut_limits
    if not limits:
        return None
    return min(float(value) for value in limits.values())


def _effective_liquid(
    events: Sequence[ControlEvent], state: PolicyState, well: str
) -> float:
    observation = state.wells[well]
    liquid = observation.liquid_rate_m3_per_day
    for event in events:
        if event.well != well:
            continue
        if event.kind is EventKind.SHUT:
            return 0.0
        if event.kind is EventKind.SET_LRAT and event.value is not None:
            liquid = event.value
    return liquid


def _shut_wells(events: Sequence[ControlEvent]) -> frozenset[str]:
    return frozenset(
        event.well for event in events if event.kind is EventKind.SHUT
    )


def watercut_cap_shutins(
    state: PolicyState,
    context: RuleContext,
    events: Sequence[ControlEvent],
    wells: Sequence[str],
    limit: float,
) -> tuple[tuple[str, ...], float, float]:
    density = context.oil_density_t_per_m3
    already_shut = _shut_wells(events)
    candidates: list[tuple[float, str, float, float]] = []
    oil_total = 0.0
    liquid_total = 0.0
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.PROD:
            continue
        if not observation.is_open or well in already_shut:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        liquid = _effective_liquid(events, state, well)
        if liquid <= 0.0:
            continue
        share = liquid / observation.liquid_rate_m3_per_day
        oil_volume = (
            observation.oil_rate_t_per_day / density
        ) * share
        oil_total += oil_volume
        liquid_total += liquid
        candidates.append(
            (observation.watercut(density), well, liquid, oil_volume)
        )
    if liquid_total <= 0.0:
        return (), 0.0, 0.0
    before = 1.0 - oil_total / liquid_total
    if before <= limit:
        return (), before, before
    ordered = sorted(candidates, key=lambda item: (-item[0], item[1]))
    shut: list[str] = []
    current = before
    for _watercut, well, liquid, oil_volume in ordered:
        if current <= limit:
            break
        liquid_total -= liquid
        oil_total -= oil_volume
        shut.append(well)
        if liquid_total <= 0.0:
            current = 0.0
            break
        current = 1.0 - oil_total / liquid_total
    if current > limit:
        raise ValueError(
            f"потолок обводнённости {limit} недостижим глушением: "
            f"на участке остаётся {current}"
        )
    return tuple(shut), before, current


def rules_for_group(flags: RuleFlags) -> tuple[Rule, ...]:
    blocked = superseded(flags)
    return tuple(
        rule
        for rule in IMPLEMENTED_RULES
        if rule not in blocked and flags.is_on(rule)
    )


def decide_group(
    state: PolicyState,
    context: RuleContext,
    theta: Theta,
    flags: RuleFlags,
    limit: GroupLimit,
) -> GroupDecision:
    if context.groups is None:
        raise ValueError("агент участка требует Groups")
    wells = tuple(sorted(context.groups.groups[limit.group_id]))
    inside = restrict(state, wells)
    scoped = replace(
        context,
        injection_budget_m3_per_day=limit.injection_m3_per_day,
        liquid_budget_m3_per_day=limit.liquid_m3_per_day,
    )
    decisions: list[ControlEvent] = []
    rule_by_decision: list[Rule] = []
    entries: list[TraceEntry] = []
    for rule in rules_for_group(flags):
        outcome: RuleOutcome = apply_rule(rule, inside, scoped, theta, flags)
        for event in outcome.decisions:
            decisions.append(event)
            rule_by_decision.append(rule)
        entries.extend(outcome.trace)

    requested = _requested_injection(tuple(decisions), inside, wells)
    factor = 1.0
    if requested > limit.injection_m3_per_day + WELL_LIMIT_TOLERANCE_M3_PER_DAY:
        if requested <= 0.0:
            raise ValueError(
                f"участок {limit.group_id}: запрос {requested} превышает лимит "
                f"{limit.injection_m3_per_day} при неположительной сумме"
            )
        factor = limit.injection_m3_per_day / requested
        for well in _untouched_injectors(tuple(decisions), inside, wells):
            observation = inside.wells[well]
            decisions.append(
                ControlEvent(
                    control_step=state.control_step,
                    well=well,
                    kind=EventKind.SET_RATE,
                    value=observation.injection_rate_m3_per_day,
                )
            )
            rule_by_decision.append(Rule.R1)
            entries.append(
                TraceEntry(
                    control_step=state.control_step,
                    well=well,
                    rule=Rule.R1,
                    inputs={
                        "group_limit_m3_per_day": limit.injection_m3_per_day,
                        "previous_setpoint_m3_per_day": (
                            observation.setpoint_m3_per_day
                        ),
                        "target_rate_m3_per_day": (
                            observation.injection_rate_m3_per_day
                        ),
                    },
                    decision="SET_RATE",
                )
            )
        decisions = [_scale_event(event, factor) for event in decisions]
        entries = [_scale_entry(entry, factor) for entry in entries]
    granted = _requested_injection(tuple(decisions), inside, wells)

    liquid_quota = limit.liquid_m3_per_day
    liquid_factor = 1.0
    liquid_requested = 0.0
    liquid_granted = 0.0
    if liquid_quota is not None:
        liquid_requested = _requested_liquid(tuple(decisions), inside, wells)
        if liquid_requested > liquid_quota + WELL_LIMIT_TOLERANCE_M3_PER_DAY:
            if liquid_requested <= 0.0:
                raise ValueError(
                    f"участок {limit.group_id}: запрос жидкости "
                    f"{liquid_requested} превышает квоту {liquid_quota} "
                    f"при неположительной сумме"
                )
            liquid_factor = liquid_quota / liquid_requested
            for well in _untouched_producers(tuple(decisions), inside, wells):
                observation = inside.wells[well]
                decisions.append(
                    ControlEvent(
                        control_step=state.control_step,
                        well=well,
                        kind=EventKind.SET_LRAT,
                        value=observation.liquid_rate_m3_per_day,
                    )
                )
                rule_by_decision.append(Rule.R2)
                entries.append(
                    TraceEntry(
                        control_step=state.control_step,
                        well=well,
                        rule=Rule.R2,
                        inputs={
                            "group_liquid_limit_m3_per_day": liquid_quota,
                            "previous_setpoint_m3_per_day": (
                                observation.setpoint_m3_per_day
                            ),
                            "target_rate_m3_per_day": (
                                observation.liquid_rate_m3_per_day
                            ),
                        },
                        decision="SET_LRAT",
                    )
                )
            decisions = [
                _scale_liquid_event(event, liquid_factor) for event in decisions
            ]
            entries = [
                _scale_liquid_entry(entry, liquid_factor) for entry in entries
            ]
        liquid_granted = _requested_liquid(tuple(decisions), inside, wells)

    watercut_entries: list[TraceEntry] = []
    if flags.feature_on(WATERCUT_CAP_FEATURE) and flags.is_on(Rule.R0):
        watercut_limit = binding_watercut_limit(context)
        if watercut_limit is not None:
            shut, before, after = watercut_cap_shutins(
                inside, context, tuple(decisions), wells, watercut_limit
            )
            for well in shut:
                observation = inside.wells[well]
                decisions.append(
                    ControlEvent(
                        control_step=state.control_step,
                        well=well,
                        kind=EventKind.SHUT,
                    )
                )
                rule_by_decision.append(Rule.R0)
                watercut_entries.append(
                    TraceEntry(
                        control_step=state.control_step,
                        well=well,
                        rule=Rule.R0,
                        inputs={
                            "watercut": observation.watercut(
                                context.oil_density_t_per_m3
                            ),
                            "watercut_limit": watercut_limit,
                            "group_watercut_before": before,
                            "group_watercut_after": after,
                            "liquid_rate_m3_per_day": (
                                observation.liquid_rate_m3_per_day
                            ),
                        },
                        decision="SHUT_TO_WATERCUT_LIMIT",
                    )
                )

    entries.extend(watercut_entries)
    if flags.is_on(Rule.R0):
        floor_check = check_production_floor(
            inside, context, tuple(decisions), wells, None
        )
        if floor_check.attempted:
            entries.append(
                floor_check.as_entry(state.control_step, limit.group_id)
            )
    trace = [
        LeveledTraceEntry(level=Level.GROUP, agent=limit.group_id, entry=entry)
        for entry in entries
    ]
    if factor < 1.0:
        trace.append(
            LeveledTraceEntry(
                level=Level.GROUP,
                agent=limit.group_id,
                entry=TraceEntry(
                    control_step=state.control_step,
                    well=limit.group_id,
                    rule=Rule.R1,
                    inputs={
                        "group_limit_m3_per_day": limit.injection_m3_per_day,
                        "requested_injection_m3_per_day": requested,
                        "group_limit_scale": factor,
                        "granted_injection_m3_per_day": granted,
                    },
                    decision="SCALE_TO_GROUP_LIMIT",
                ),
            )
        )
    if liquid_quota is not None and liquid_factor < 1.0:
        trace.append(
            LeveledTraceEntry(
                level=Level.GROUP,
                agent=limit.group_id,
                entry=TraceEntry(
                    control_step=state.control_step,
                    well=limit.group_id,
                    rule=Rule.R2,
                    inputs={
                        "group_liquid_limit_m3_per_day": liquid_quota,
                        "requested_liquid_m3_per_day": liquid_requested,
                        "group_liquid_limit_scale": liquid_factor,
                        "granted_liquid_m3_per_day": liquid_granted,
                    },
                    decision="SCALE_TO_GROUP_LIQUID_LIMIT",
                ),
            )
        )
    return GroupDecision(
        group_id=limit.group_id,
        limit=limit,
        decisions=tuple(decisions),
        rule_by_decision=tuple(rule_by_decision),
        trace=tuple(trace),
        requested_injection_m3_per_day=granted,
        requested_liquid_m3_per_day=(
            liquid_granted if liquid_quota is not None else None
        ),
    )


def _outage_steps(context: RuleContext, well: str) -> tuple[int, int] | None:
    for outage in context.constraints.well_outages:
        if outage.well != well:
            continue
        return outage.control_step_from, outage.control_step_to
    return None


def _quantized(value: float, step_m3_per_day: float | None) -> float:
    if step_m3_per_day is None:
        return value
    if step_m3_per_day <= 0.0:
        raise ValueError(f"шаг квантования {step_m3_per_day} не положителен")
    return round(value / step_m3_per_day) * step_m3_per_day


def execute_well(
    state: PolicyState,
    context: RuleContext,
    event: ControlEvent,
    rule: Rule,
    agent: str,
    setpoint_step_m3_per_day: float | None = None,
) -> tuple[ControlEvent | None, LeveledTraceEntry]:
    observation = state.wells.get(event.well)
    if observation is None:
        raise ValueError(
            f"{event.well}: исполнитель не видит состояния скважины, "
            f"валидировать физику нечем"
        )
    inputs: dict[str, float] = {
        "control_step": float(event.control_step),
        "liquid_rate_m3_per_day": observation.liquid_rate_m3_per_day,
        "injection_rate_m3_per_day": observation.injection_rate_m3_per_day,
        "previous_setpoint_m3_per_day": observation.setpoint_m3_per_day,
    }
    outage = _outage_steps(context, event.well)
    if outage is not None:
        inputs["outage_from"] = float(outage[0])
        inputs["outage_to"] = float(outage[1])
        if outage[0] <= event.control_step <= outage[1]:
            return None, _well_entry(event, rule, agent, inputs, "VETO_OUTAGE")
    if event.value is None:
        return event, _well_entry(event, rule, agent, inputs, event.kind.value)
    quantized = _quantized(event.value, setpoint_step_m3_per_day)
    inputs["requested_value_m3_per_day"] = event.value
    if setpoint_step_m3_per_day is not None:
        inputs["setpoint_step_m3_per_day"] = setpoint_step_m3_per_day
    if event.kind is EventKind.SET_LRAT:
        inputs["lrat_ceiling_m3_per_day"] = MAX_LRAT_M3_PER_DAY
        quantized = min(quantized, MAX_LRAT_M3_PER_DAY)
    quantized = max(quantized, 0.0)
    inputs["applied_value_m3_per_day"] = quantized
    return (
        replace(event, value=quantized),
        _well_entry(event, rule, agent, inputs, event.kind.value),
    )


def _well_entry(
    event: ControlEvent,
    rule: Rule,
    agent: str,
    inputs: dict[str, float],
    decision: str,
) -> LeveledTraceEntry:
    return LeveledTraceEntry(
        level=Level.WELL,
        agent=agent,
        entry=TraceEntry(
            control_step=event.control_step,
            well=event.well,
            rule=rule,
            inputs=inputs,
            decision=decision,
        ),
    )


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


def wells_without_group(groups: Groups, wells: Sequence[str]) -> tuple[str, ...]:
    covered = {well for members in groups.groups.values() for well in members}
    return tuple(sorted(well for well in wells if well not in covered))


def observations_by_group(
    state: PolicyState, groups: Groups
) -> dict[str, tuple[WellObservation, ...]]:
    collected: dict[str, tuple[WellObservation, ...]] = {}
    for group_id in sorted(groups.groups):
        collected[group_id] = tuple(
            state.wells[well]
            for well in sorted(groups.groups[group_id])
            if well in state.wells
        )
    return collected
