from __future__ import annotations

from contracts import ControlEvent, EventKind, Role, Rule, Theta, TraceEntry

from policy.economics import DAYS_PER_YEAR, annual_margin_rub
from policy.rules.r1 import marginal_value_rub_per_m3
from policy.rules.base import RuleOutcome
from policy.state import PolicyState, RuleContext
from policy.theta import read

RULE = Rule.R6
ADMISSION_CRITERION = (
    "Переводим, когда как нагнетательная она дороже, чем как добывающая."
)
THETA_NAMES: tuple[str, ...] = ("r6_payback_years",)


def annual_injection_value_rub(
    marginal_value_rub_per_m3_water: float, injection_m3_per_day: float
) -> float:
    return marginal_value_rub_per_m3_water * injection_m3_per_day * DAYS_PER_YEAR


def payback_years(conversion_cost_rub: float, annual_delta_rub: float) -> float:
    if annual_delta_rub <= 0.0:
        return float("inf")
    return conversion_cost_rub / annual_delta_rub


def apply(state: PolicyState, context: RuleContext, theta: Theta) -> RuleOutcome:
    horizon = read(theta, "r6_payback_years")
    influence = context.influence
    if influence is None:
        raise ValueError(
            "R6 требует измеренную λ: ценность скважины как нагнетательной "
            "без матрицы влияния не определена"
        )
    normatives = context.normatives
    density = context.oil_density_t_per_m3
    decisions: list[ControlEvent] = []
    trace: list[TraceEntry] = []
    for well in sorted(state.wells):
        observation = state.wells[well]
        if observation.role is not Role.PROD or not observation.is_open:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        if context.memory.of(well).converted_to_injection:
            continue
        if well not in influence.injectors:
            continue
        watercut = observation.watercut(density)
        as_producer = annual_margin_rub(
            normatives, density, observation.liquid_rate_m3_per_day, watercut
        )
        value_per_m3, value_inputs = marginal_value_rub_per_m3(
            state, context, well
        )
        capacity = observation.liquid_rate_m3_per_day
        as_injector = annual_injection_value_rub(value_per_m3, capacity)
        delta = as_injector - as_producer
        cost = normatives.conversion_base_cost_rub
        years = payback_years(cost, delta)
        inputs = {
            "liquid_rate_m3_per_day": observation.liquid_rate_m3_per_day,
            "watercut": watercut,
            "annual_margin_as_producer_rub": as_producer,
            "marginal_value_rub_per_m3": value_per_m3,
            "assumed_injection_m3_per_day": capacity,
            "annual_value_as_injector_rub": as_injector,
            "annual_delta_rub": delta,
            "conversion_base_cost_rub": cost,
            "payback_years": years,
            "theta_r6_payback_years": horizon,
            "gross_value_rub_per_m3": value_inputs["gross_value_rub_per_m3"],
            "opex_injection_rub_per_m3": value_inputs[
                "opex_injection_rub_per_m3"
            ],
        }
        if years > horizon:
            trace.append(
                TraceEntry(
                    control_step=state.control_step,
                    well=well,
                    rule=RULE,
                    inputs=inputs,
                    decision="HOLD_AS_PRODUCER",
                )
            )
            continue
        decisions.append(
            ControlEvent(
                control_step=state.control_step,
                well=well,
                kind=EventKind.CONVERT_INJ,
            )
        )
        trace.append(
            TraceEntry(
                control_step=state.control_step,
                well=well,
                rule=RULE,
                inputs=inputs,
                decision="CONVERT_INJ",
            )
        )
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))
