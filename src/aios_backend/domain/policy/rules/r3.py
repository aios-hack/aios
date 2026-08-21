from __future__ import annotations

from aios_backend.core.contracts import ControlEvent, EventKind, Role, Rule, Theta, TraceEntry

from aios_backend.domain.policy.economics import annual_margin_rub, breakeven_watercut
from aios_backend.domain.policy.memory import WellMemory
from aios_backend.domain.policy.rules.base import RuleOutcome
from aios_backend.domain.policy.state import PolicyState, RuleContext
from aios_backend.domain.policy.theta import read

RULE = Rule.R3
ADMISSION_CRITERION = (
    "Закрываем после N месяцев убытка, открываем только с запасом."
)
THETA_NAMES: tuple[str, ...] = ("r3_months_in_loss", "r3_reopen_margin")


def reopen_threshold(breakeven: float, margin: float) -> float:
    return breakeven * (1.0 - margin)


def shut_is_confirmed(memory: WellMemory, months_in_loss: float) -> bool:
    return memory.months_in_loss + 1 >= months_in_loss


def apply(state: PolicyState, context: RuleContext, theta: Theta) -> RuleOutcome:
    months_in_loss = read(theta, "r3_months_in_loss")
    reopen_margin = read(theta, "r3_reopen_margin")
    density = context.oil_density_t_per_m3
    normatives = context.normatives
    decisions: list[ControlEvent] = []
    trace: list[TraceEntry] = []
    for well in sorted(state.wells):
        observation = state.wells[well]
        if observation.role is not Role.PROD:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        memory = context.memory.of(well)
        watercut = observation.watercut(density)
        margin = annual_margin_rub(
            normatives, density, observation.liquid_rate_m3_per_day, watercut
        )
        breakeven = breakeven_watercut(
            normatives, density, observation.liquid_rate_m3_per_day
        )
        inputs = {
            "liquid_rate_m3_per_day": observation.liquid_rate_m3_per_day,
            "watercut": watercut,
            "breakeven_watercut": breakeven,
            "annual_margin_rub": margin,
            "months_in_loss": float(memory.months_in_loss),
            "months_in_profit": float(memory.months_in_profit),
            "theta_r3_months_in_loss": months_in_loss,
            "theta_r3_reopen_margin": reopen_margin,
            "event_cost_rub": normatives.event_cost_rub,
        }
        if observation.is_open:
            if margin >= 0.0:
                continue
            if shut_is_confirmed(memory, months_in_loss):
                decisions.append(
                    ControlEvent(
                        control_step=state.control_step,
                        well=well,
                        kind=EventKind.SHUT,
                    )
                )
                trace.append(
                    TraceEntry(
                        control_step=state.control_step,
                        well=well,
                        rule=RULE,
                        inputs=inputs,
                        decision="SHUT",
                    )
                )
                continue
            trace.append(
                TraceEntry(
                    control_step=state.control_step,
                    well=well,
                    rule=RULE,
                    inputs=inputs,
                    decision="HOLD_OPEN",
                )
            )
            continue
        threshold = reopen_threshold(breakeven, reopen_margin)
        inputs["reopen_watercut_threshold"] = threshold
        if watercut <= threshold and margin > 0.0:
            decisions.append(
                ControlEvent(
                    control_step=state.control_step,
                    well=well,
                    kind=EventKind.OPEN,
                )
            )
            trace.append(
                TraceEntry(
                    control_step=state.control_step,
                    well=well,
                    rule=RULE,
                    inputs=inputs,
                    decision="OPEN",
                )
            )
            continue
        trace.append(
            TraceEntry(
                control_step=state.control_step,
                well=well,
                rule=RULE,
                inputs=inputs,
                decision="HOLD_SHUT",
            )
        )
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))


def advance(
    state: PolicyState, context: RuleContext, well: str
) -> WellMemory:
    observation = state.wells[well]
    memory = context.memory.of(well)
    if observation.liquid_rate_m3_per_day <= 0.0:
        return memory
    margin = annual_margin_rub(
        context.normatives,
        context.oil_density_t_per_m3,
        observation.liquid_rate_m3_per_day,
        observation.watercut(context.oil_density_t_per_m3),
    )
    return memory.with_loss() if margin < 0.0 else memory.with_profit()
