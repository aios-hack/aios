from __future__ import annotations

from backend.contexts.policy.domain.hierarchy_shared import (
    WELL_LIMIT_TOLERANCE_M3_PER_DAY,
    restrict,
)


from backend.contexts.policy.domain.levels.field import (
    GroupLimit,
    _requested_injection,
    _requested_liquid,
    _scale_entry,
    _scale_event,
    _scale_liquid_entry,
    _scale_liquid_event,
    _untouched_injectors,
    _untouched_producers,
)
from backend.contexts.policy.domain.watercut_shutins import (
    binding_watercut_limit,
    watercut_cap_shutins,
)
from backend.contexts.policy.domain.production_floor import (
    check_production_floor,
)
from backend.contexts.policy.domain.trace_types import (
    Level,
    LeveledTraceEntry,
)
from dataclasses import dataclass, replace
from backend.core.contracts import (
    ControlEvent,
    EventKind,
    Groups,
    Rule,
    Theta,
    TraceEntry,
)
from backend.contexts.policy.domain.flags import (
    IMPLEMENTED_RULES,
    WATERCUT_CAP_FEATURE,
    RuleFlags,
)
from backend.contexts.policy.domain.rules import apply_rule, superseded
from backend.contexts.policy.domain.rules.base import RuleOutcome
from backend.contexts.policy.domain.state import (
    PolicyState,
    RuleContext,
)


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


__all__ = [
    "GroupDecision",
    "decide_group",
    "rules_for_group",
]
