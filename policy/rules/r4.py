from __future__ import annotations

from contracts import ControlEvent, EventKind, Role, Rule, Theta, TraceEntry

from policy.economics import DAYS_PER_YEAR, oil_margin_rub_per_m3_liquid
from policy.memory import esp_size_for, esp_upgrade_cost_rub
from policy.rules.base import RuleOutcome
from policy.state import PolicyState, RuleContext

RULE = Rule.R4
ADMISSION_CRITERION = (
    "Не пересекаем границу типоразмера, если разгон не окупает насос."
)
THETA_NAMES: tuple[str, ...] = ()


def annual_gain_rub(
    normatives,
    oil_density_t_per_m3: float,
    delta_liquid_m3_per_day: float,
    watercut: float,
) -> float:
    per_m3 = oil_margin_rub_per_m3_liquid(
        normatives, oil_density_t_per_m3, watercut
    ) - normatives.opex_liquid_rub_per_t
    return delta_liquid_m3_per_day * DAYS_PER_YEAR * per_m3


def apply(state: PolicyState, context: RuleContext, theta: Theta) -> RuleOutcome:
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
        target = observation.setpoint_m3_per_day
        if target <= observation.liquid_rate_m3_per_day:
            continue
        memory = context.memory.of(well)
        needed = esp_size_for(normatives.esp_catalog, target)
        installed = memory.esp_nominal_m3_per_day
        if needed.nominal <= installed:
            continue
        capex = esp_upgrade_cost_rub(
            installed, needed, normatives.esp_swap_opex_rub
        )
        watercut = observation.watercut(density)
        delta = target - observation.liquid_rate_m3_per_day
        gain = annual_gain_rub(normatives, density, delta, watercut)
        inputs = {
            "liquid_rate_m3_per_day": observation.liquid_rate_m3_per_day,
            "requested_setpoint_m3_per_day": target,
            "delta_liquid_m3_per_day": delta,
            "watercut": watercut,
            "installed_esp_nominal_m3_per_day": installed,
            "needed_esp_nominal_m3_per_day": needed.nominal,
            "esp_capex_rub": needed.cost_rub,
            "esp_swap_opex_rub": normatives.esp_swap_opex_rub,
            "upgrade_cost_rub": capex,
            "annual_gain_rub": gain,
        }
        if gain <= 0.0:
            payback_years = float("inf")
        else:
            payback_years = capex / gain
        inputs["payback_years"] = payback_years
        if gain > 0.0 and capex <= gain:
            trace.append(
                TraceEntry(
                    control_step=state.control_step,
                    well=well,
                    rule=RULE,
                    inputs=inputs,
                    decision="ALLOW_UPSIZE",
                )
            )
            continue
        capped = min(installed, observation.liquid_rate_m3_per_day)
        if installed <= 0.0:
            capped = observation.liquid_rate_m3_per_day
        inputs["capped_setpoint_m3_per_day"] = capped
        decisions.append(
            ControlEvent(
                control_step=state.control_step,
                well=well,
                kind=EventKind.SET_LRAT,
                value=capped,
            )
        )
        trace.append(
            TraceEntry(
                control_step=state.control_step,
                well=well,
                rule=RULE,
                inputs=inputs,
                decision="CAP_AT_ESP_SIZE",
            )
        )
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))
