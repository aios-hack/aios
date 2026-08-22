from __future__ import annotations

from backend.core.contracts import ControlEvent, EventKind, Role, Rule, Theta, TraceEntry

from backend.domain.policy.economics import annual_margin_rub, breakeven_watercut, oil_margin_rub_per_t
from backend.domain.policy.rules.base import RuleOutcome
from backend.domain.policy.state import PolicyState, RuleContext

RULE = Rule.R0
ADMISSION_CRITERION = "Держим скважину, пока она отбивает своё содержание."
THETA_NAMES: tuple[str, ...] = ()


def apply(state: PolicyState, context: RuleContext, theta: Theta) -> RuleOutcome:
    decisions: list[ControlEvent] = []
    trace: list[TraceEntry] = []
    density = context.oil_density_t_per_m3
    normatives = context.normatives
    for well in sorted(state.wells):
        observation = state.wells[well]
        if observation.role is not Role.PROD or not observation.is_open:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        watercut = observation.watercut(density)
        margin = annual_margin_rub(
            normatives, density, observation.liquid_rate_m3_per_day, watercut
        )
        if margin >= 0.0:
            continue
        threshold = breakeven_watercut(
            normatives, density, observation.liquid_rate_m3_per_day
        )
        decisions.append(
            ControlEvent(control_step=state.control_step, well=well, kind=EventKind.SHUT)
        )
        trace.append(
            TraceEntry(
                control_step=state.control_step,
                well=well,
                rule=RULE,
                inputs={
                    "liquid_rate_m3_per_day": observation.liquid_rate_m3_per_day,
                    "oil_rate_t_per_day": observation.oil_rate_t_per_day,
                    "watercut": watercut,
                    "breakeven_watercut": threshold,
                    "oil_density_t_per_m3": density,
                    "oil_margin_rub_per_t": oil_margin_rub_per_t(normatives),
                    "opex_liquid_rub_per_t": normatives.opex_liquid_rub_per_t,
                    "wellstock_rub_per_year": normatives.opex_wellstock_rub_per_well_year,
                    "annual_margin_rub": margin,
                },
                decision="SHUT",
            )
        )
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))
