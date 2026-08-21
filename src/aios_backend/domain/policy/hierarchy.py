from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping, Sequence

from aios_backend.core.contracts import (
    MAX_LRAT_M3_PER_DAY,
    ControlEvent,
    EventKind,
    Groups,
    Role,
    Rule,
    Theta,
    TraceEntry,
)

from aios_backend.domain.policy.flags import IMPLEMENTED_RULES, RuleFlags
from aios_backend.domain.policy.rules import apply_rule, superseded
from aios_backend.domain.policy.rules.base import RuleOutcome
from aios_backend.domain.policy.rules.r1 import marginal_value_rub_per_m3
from aios_backend.domain.policy.state import PolicyState, RuleContext, WellObservation
from aios_backend.domain.policy.trace import RunTrace

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

    def __post_init__(self) -> None:
        if self.injection_m3_per_day < 0.0:
            raise ValueError(f"{self.group_id}: отрицательный лимит закачки")


@dataclass(frozen=True, slots=True)
class FieldAllocation:
    field_limit_m3_per_day: float
    limits: tuple[GroupLimit, ...]
    trace: tuple[LeveledTraceEntry, ...]

    def __post_init__(self) -> None:
        allocated = sum(limit.injection_m3_per_day for limit in self.limits)
        if allocated > self.field_limit_m3_per_day + WELL_LIMIT_TOLERANCE_M3_PER_DAY:
            raise ValueError(
                f"сумма лимитов участков {allocated} превышает лимит поля "
                f"{self.field_limit_m3_per_day}"
            )

    def allocated_m3_per_day(self) -> float:
        return sum(limit.injection_m3_per_day for limit in self.limits)

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
    demands: dict[str, float] = {}
    counted: dict[str, int] = {}
    for group_id in group_ids:
        demand, injectors = group_demand_rub_per_m3(
            state, context, context.groups.groups[group_id]
        )
        demands[group_id] = demand
        counted[group_id] = injectors
    total_demand = sum(demands.values())

    limits: list[GroupLimit] = []
    trace: list[LeveledTraceEntry] = []
    for group_id in group_ids:
        demand = demands[group_id]
        if total_demand > 0.0:
            share = demand / total_demand
        else:
            share = 0.0
        allocated = limit * share
        limits.append(
            GroupLimit(
                group_id=group_id,
                injection_m3_per_day=allocated,
                share_of_field=share,
                demand_rub_per_m3=demand,
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
    return FieldAllocation(
        field_limit_m3_per_day=limit,
        limits=tuple(limits),
        trace=tuple(trace),
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
    return GroupDecision(
        group_id=limit.group_id,
        limit=limit,
        decisions=tuple(decisions),
        rule_by_decision=tuple(rule_by_decision),
        trace=tuple(trace),
        requested_injection_m3_per_day=granted,
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


def run_step(
    state: PolicyState,
    context: RuleContext,
    theta: Theta,
    flags: RuleFlags,
    field_limit_m3_per_day: float | None = None,
    setpoint_step_m3_per_day: float | None = None,
) -> HierarchyResult:
    allocation = allocate_field(state, context, flags, field_limit_m3_per_day)
    group_decisions: list[GroupDecision] = []
    decisions: list[ControlEvent] = []
    trace: list[LeveledTraceEntry] = list(allocation.trace)
    for limit in allocation.limits:
        decision = decide_group(state, context, theta, flags, limit)
        group_decisions.append(decision)
        trace.extend(decision.trace)
        for event, rule in zip(decision.decisions, decision.rule_by_decision):
            applied, entry = execute_well(
                state,
                context,
                event,
                rule=rule,
                agent=event.well,
                setpoint_step_m3_per_day=setpoint_step_m3_per_day,
            )
            trace.append(entry)
            if applied is not None:
                decisions.append(applied)
    return HierarchyResult(
        allocation=allocation,
        group_decisions=tuple(group_decisions),
        decisions=tuple(decisions),
        trace=HierarchyTrace(entries=tuple(trace), flags=flags),
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
