from __future__ import annotations

from aios_backend.core.contracts import (
    MAX_LRAT_M3_PER_DAY,
    ControlEvent,
    EventKind,
    Role,
    Rule,
    Theta,
    TraceEntry,
)

from aios_backend.domain.policy.rules.base import RuleOutcome
from aios_backend.domain.policy.state import PolicyState, RuleContext
from aios_backend.domain.policy.theta import read

RULE = Rule.R2
ADMISSION_CRITERION = "Разгоняем чистые скважины, душим обводнённые."
THETA_NAMES: tuple[str, ...] = ("r2_watercut_pivot", "r2_gain")


def target_rate_m3_per_day(
    liquid_rate_m3_per_day: float, watercut: float, pivot: float, gain: float
) -> float:
    factor = 1.0 + gain * (pivot - watercut) / max(pivot, 1.0 - pivot)
    target = liquid_rate_m3_per_day * max(factor, 0.0)
    return min(target, MAX_LRAT_M3_PER_DAY)


def apply(state: PolicyState, context: RuleContext, theta: Theta) -> RuleOutcome:
    pivot = read(theta, "r2_watercut_pivot")
    gain = read(theta, "r2_gain")
    density = context.oil_density_t_per_m3
    decisions: list[ControlEvent] = []
    trace: list[TraceEntry] = []
    for well in sorted(state.wells):
        observation = state.wells[well]
        if observation.role is not Role.PROD or not observation.is_open:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        watercut = observation.watercut(density)
        target = target_rate_m3_per_day(
            observation.liquid_rate_m3_per_day, watercut, pivot, gain
        )
        if target == observation.setpoint_m3_per_day:
            continue
        decisions.append(
            ControlEvent(
                control_step=state.control_step,
                well=well,
                kind=EventKind.SET_LRAT,
                value=target,
            )
        )
        trace.append(
            TraceEntry(
                control_step=state.control_step,
                well=well,
                rule=RULE,
                inputs={
                    "liquid_rate_m3_per_day": observation.liquid_rate_m3_per_day,
                    "watercut": watercut,
                    "theta_r2_watercut_pivot": pivot,
                    "theta_r2_gain": gain,
                    "previous_setpoint_m3_per_day": observation.setpoint_m3_per_day,
                    "target_rate_m3_per_day": target,
                    "lrat_ceiling_m3_per_day": MAX_LRAT_M3_PER_DAY,
                },
                decision="SET_LRAT",
            )
        )
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))
