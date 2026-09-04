"""Шаг иерархии: реестр агентов вызывает уровни в объявленном порядке.

Механики уровней живут в `policy/levels.py`, роли и порядок вызова — в
`policy/agents/`. Здесь только сборка шага и имя агента в каждой записи
журнала, которое берётся из реестра, а не пишется строкой по месту.
"""

from __future__ import annotations

from backend.core.contracts import Theta

from backend.domain.policy.agents.registry import DEFAULT_REGISTRY, AgentRegistry
from backend.domain.policy.flags import RuleFlags
from backend.domain.policy.levels import (
    FIELD_AGENT,
    WELL_LIMIT_TOLERANCE_M3_PER_DAY,
    FieldAllocation,
    GroupDecision,
    GroupLimit,
    HierarchyResult,
    HierarchyTrace,
    Level,
    LeveledTraceEntry,
    allocate_field,
    decide_group,
    execute_well,
    field_limit_from_constraints,
    group_demand_rub_per_m3,
    group_of,
    observations_by_group,
    restrict,
    rules_for_group,
    wells_without_group,
)
from backend.domain.policy.state import PolicyState, RuleContext, WellObservation

__all__ = [
    "FIELD_AGENT",
    "WELL_LIMIT_TOLERANCE_M3_PER_DAY",
    "FieldAllocation",
    "GroupDecision",
    "GroupLimit",
    "HierarchyResult",
    "HierarchyTrace",
    "Level",
    "LeveledTraceEntry",
    "PolicyState",
    "RuleContext",
    "WellObservation",
    "allocate_field",
    "decide_group",
    "execute_well",
    "field_limit_from_constraints",
    "group_demand_rub_per_m3",
    "group_of",
    "observations_by_group",
    "restrict",
    "rules_for_group",
    "run_step",
    "wells_without_group",
]


def run_step(
    state: PolicyState,
    context: RuleContext,
    theta: Theta,
    flags: RuleFlags,
    field_limit_m3_per_day: float | None = None,
    setpoint_step_m3_per_day: float | None = None,
    registry: AgentRegistry = DEFAULT_REGISTRY,
) -> HierarchyResult:
    coordinator = registry.one_of_level(Level.FIELD)
    allocator = registry.one_of_level(Level.GROUP)
    executor = registry.one_of_level(Level.WELL)

    allocation = coordinator.allocate(state, context, flags, field_limit_m3_per_day)
    group_decisions: list[GroupDecision] = []
    decisions = []
    trace: list[LeveledTraceEntry] = list(allocation.trace)
    for limit in allocation.limits:
        decision = allocator.decide(state, context, theta, flags, limit)
        group_decisions.append(decision)
        trace.extend(decision.trace)
        for event, rule in zip(decision.decisions, decision.rule_by_decision):
            applied, entry = executor.execute(
                state,
                context,
                event,
                rule,
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
