from __future__ import annotations

from backend.contexts.policy.domain.levels.group import (
    _outage_steps,
    _quantized,
)
from backend.contexts.policy.domain.trace_types import (
    Level,
    LeveledTraceEntry,
)
from dataclasses import (
    replace,
)
from backend.core.contracts import (
    MAX_LRAT_M3_PER_DAY,
    ControlEvent,
    EventKind,
    Rule,
    TraceEntry,
)
from backend.contexts.policy.domain.state import (
    PolicyState,
    RuleContext,
)


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


__all__ = [
    "execute_well",
]
