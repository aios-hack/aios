from __future__ import annotations

from contracts import ControlEvent, EventKind, NormativeSet, Role, Rule, Theta, TraceEntry

from policy.economics import annual_margin_rub
from policy.rules.base import RuleOutcome
from policy.state import PolicyState, RuleContext
from policy.theta import read

RULE = Rule.R7
ADMISSION_CRITERION = (
    "Периодически останавливаем высокообводнённые, чтобы вовлечь защемлённое."
)
THETA_NAMES: tuple[str, ...] = ("r7_cycle_months", "r7_watercut_floor")

EVENTS_PER_CYCLE = 2.0
PHASES_PER_CYCLE = 2
MONTHS_PER_YEAR = 12.0

BENEFIT_UNCONFIRMED = (
    "Выгода циклики данными не подтверждена: без измеренного прироста "
    "правило не срабатывает и остаётся гипотезой. Флаг по умолчанию выключен."
)


def cycle_cost_rub(event_cost_rub: float) -> float:
    return EVENTS_PER_CYCLE * event_cost_rub


def cycle_period_months(cycle_months: float) -> int:
    period = int(cycle_months)
    if period <= 0:
        raise ValueError(f"период цикла {cycle_months} не положителен")
    return period


def is_rest_phase(control_step: int, cycle_months: float) -> bool:
    period = cycle_period_months(cycle_months)
    return (control_step // period) % PHASES_PER_CYCLE == 1


def foregone_margin_rub(
    normatives: NormativeSet,
    oil_density_t_per_m3: float,
    liquid_rate_m3_per_day: float,
    watercut: float,
    cycle_months: float,
) -> float:
    annual = annual_margin_rub(
        normatives, oil_density_t_per_m3, liquid_rate_m3_per_day, watercut
    )
    if annual <= 0.0:
        return 0.0
    return annual * cycle_months / MONTHS_PER_YEAR


def cycle_is_justified(
    uplift_rub: float, cost_rub: float, foregone_rub: float
) -> bool:
    return uplift_rub > cost_rub + foregone_rub


def measured_uplift_rub(context: RuleContext, well: str) -> float:
    measured = context.cyclic_uplift_rub_per_well
    if not measured:
        return 0.0
    return measured.get(well, 0.0)


def apply(state: PolicyState, context: RuleContext, theta: Theta) -> RuleOutcome:
    cycle_months = read(theta, "r7_cycle_months")
    watercut_floor = read(theta, "r7_watercut_floor")
    density = context.oil_density_t_per_m3
    normatives = context.normatives
    cost = cycle_cost_rub(normatives.event_cost_rub)
    rest = is_rest_phase(state.control_step, cycle_months)
    decisions: list[ControlEvent] = []
    trace: list[TraceEntry] = []
    for well in sorted(state.wells):
        observation = state.wells[well]
        if observation.role is not Role.PROD:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        if context.memory.of(well).converted_to_injection:
            continue
        watercut = observation.watercut(density)
        if watercut < watercut_floor:
            continue
        foregone = foregone_margin_rub(
            normatives,
            density,
            observation.liquid_rate_m3_per_day,
            watercut,
            cycle_months,
        )
        uplift = measured_uplift_rub(context, well)
        inputs = {
            "liquid_rate_m3_per_day": observation.liquid_rate_m3_per_day,
            "watercut": watercut,
            "theta_r7_cycle_months": cycle_months,
            "theta_r7_watercut_floor": watercut_floor,
            "event_cost_rub": normatives.event_cost_rub,
            "cycle_cost_rub": cost,
            "foregone_margin_rub": foregone,
            "measured_cyclic_uplift_rub": uplift,
            "in_rest_phase": float(rest),
        }
        if not cycle_is_justified(uplift, cost, foregone):
            trace.append(
                TraceEntry(
                    control_step=state.control_step,
                    well=well,
                    rule=RULE,
                    inputs=inputs,
                    decision="NO_CYCLE_UPLIFT_NOT_MEASURED",
                )
            )
            continue
        if rest and observation.is_open:
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
                    decision="CYCLE_SHUT",
                )
            )
            continue
        if not rest and not observation.is_open:
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
                    decision="CYCLE_OPEN",
                )
            )
            continue
        trace.append(
            TraceEntry(
                control_step=state.control_step,
                well=well,
                rule=RULE,
                inputs=inputs,
                decision="HOLD_PHASE",
            )
        )
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))
