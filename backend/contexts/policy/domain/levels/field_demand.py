from __future__ import annotations

from typing import Mapping, Sequence

from backend.contexts.connectivity.domain.connectivity import Groups
from backend.contexts.policy.domain.economics import oil_margin_rub_per_m3_liquid
from backend.contexts.policy.domain.hierarchy_shared import FIELD_AGENT
from backend.contexts.policy.domain.policy import Rule, TraceEntry
from backend.contexts.policy.domain.flags import RuleFlags
from backend.contexts.policy.domain.rules.r1 import marginal_value_rub_per_m3
from backend.contexts.policy.domain.state import PolicyState, RuleContext
from backend.contexts.policy.domain.trace_types import Level, LeveledTraceEntry
from backend.contexts.schedule.domain.schedule import Role

def group_demand_rub_per_m3(
    state: PolicyState, context: RuleContext, wells: Sequence[str]
) -> tuple[float, int]:
    influence = context.influence
    if influence is None:
        raise ValueError(
            "the field manager requires a measured λ: the group demand for "
            "water is undefined without the influence matrix"
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
