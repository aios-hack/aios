from __future__ import annotations

from backend.core.contracts import ControlEvent, Rule, Theta

from backend.domain.policy.agents.base import (
    Agent,
    Bound,
    Proposal,
    Verdict,
    merge_proposals,
)
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
    group_liquid_demand_rub_per_day,
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
    "group_liquid_demand_rub_per_day",
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
    field_liquid_limit_m3_per_day: float | None = None,
    setpoint_step_m3_per_day: float | None = None,
    registry: AgentRegistry = DEFAULT_REGISTRY,
) -> HierarchyResult:
    field_agents = registry.by_level(Level.FIELD)
    group_agents = registry.by_level(Level.GROUP)
    well_agents = registry.by_level(Level.WELL)
    _require_level_is_served(field_agents, Level.FIELD)
    _require_level_is_served(group_agents, Level.GROUP)
    _require_level_is_served(well_agents, Level.WELL)

    coordinator = field_agents[0]
    allocator = group_agents[0]
    executor = well_agents[0]

    allocation = coordinator.allocate(
        state,
        context,
        flags,
        field_limit_m3_per_day,
        field_liquid_limit_m3_per_day,
    )
    group_decisions: list[GroupDecision] = []
    decisions = []
    trace: list[LeveledTraceEntry] = list(allocation.trace)
    field_bounds = _bounds_of_followers(
        field_agents,
        Level.FIELD,
        coordinator.trace_agent,
        state,
        context,
        trace,
        Rule.R1,
    )
    for limit in allocation.limits:
        decision = allocator.decide(state, context, theta, flags, limit)
        group_decisions.append(decision)
        trace.extend(decision.trace)
        group_bounds = field_bounds + _bounds_of_followers(
            group_agents,
            Level.GROUP,
            allocator.trace_agent_for(limit),
            state,
            context,
            trace,
            Rule.R1,
        )
        for event, rule in zip(decision.decisions, decision.rule_by_decision):
            applied, entry = executor.execute(
                state,
                context,
                event,
                rule,
                setpoint_step_m3_per_day=setpoint_step_m3_per_day,
            )
            trace.append(entry)
            if applied is None:
                continue
            applied = _restricted_by_followers(
                applied,
                rule,
                well_agents,
                group_bounds,
                executor.trace_agent_for(event),
                state,
                context,
                trace,
            )
            if applied is not None:
                decisions.append(applied)
    return HierarchyResult(
        allocation=allocation,
        group_decisions=tuple(group_decisions),
        decisions=tuple(decisions),
        trace=HierarchyTrace(entries=tuple(trace), flags=flags),
    )


def _require_level_is_served(agents: tuple[Agent, ...], level: Level) -> None:
    if not agents:
        raise ValueError(
            f"уровень {level.value} не обслуживает ни один агент: шаг "
            f"иерархии посчитать нечем"
        )


def _bounds_of_followers(
    agents: tuple[Agent, ...],
    level: Level,
    primary_agent: str,
    state: PolicyState,
    context: RuleContext,
    trace: list[LeveledTraceEntry],
    rule: Rule,
) -> tuple[Bound, ...]:
    if len(agents) == 1:
        return ()
    proposals = [
        Proposal(
            level=level,
            agent=primary_agent,
            decisions=(),
            rule_by_decision=(),
            trace=(),
        )
    ]
    for agent in agents[1:]:
        proposals.append(agent.propose(state, context))
    merged = merge_proposals(tuple(proposals), state.control_step, rule)
    trace.extend(merged.trace)
    if merged.verdict is Verdict.VETO:
        raise ValueError(
            f"уровень {level.value}: агент наложил вето "
            f"«{merged.veto_reason}» на весь уровень — распространить его на "
            f"отдельные решения нечем"
        )
    return merged.bounds


def _restricted_by_followers(
    applied: ControlEvent,
    rule: Rule,
    agents: tuple[Agent, ...],
    inherited: tuple[Bound, ...],
    primary_agent: str,
    state: PolicyState,
    context: RuleContext,
    trace: list[LeveledTraceEntry],
) -> ControlEvent | None:
    if len(agents) == 1 and not inherited:
        return applied
    proposals = [
        Proposal(
            level=Level.WELL,
            agent=primary_agent,
            decisions=(applied,),
            rule_by_decision=(rule,),
            trace=(),
            bounds=inherited,
        )
    ]
    for agent in agents[1:]:
        proposals.append(agent.propose(state, context))
    merged = merge_proposals(tuple(proposals), state.control_step, rule)
    trace.extend(merged.trace)
    if merged.verdict is Verdict.VETO:
        return None
    if not merged.decisions:
        return None
    return merged.decisions[0]
