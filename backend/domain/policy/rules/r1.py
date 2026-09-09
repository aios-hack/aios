from __future__ import annotations

from typing import Mapping

from backend.core.contracts import ControlEvent, EventKind, Role, Rule, Theta, TraceEntry

from backend.domain.policy.economics import oil_margin_rub_per_m3_liquid, oil_margin_rub_per_t
from backend.domain.policy.rules.base import RuleOutcome
from backend.domain.policy.state import PolicyState, RuleContext
from backend.domain.policy.theta import read

RULE = Rule.R1
ADMISSION_CRITERION = (
    "Вода течёт к тем скважинам, где она превращается в нефть, а не в воду."
)
THETA_NAMES: tuple[str, ...] = ("r1_lag_months",)


def marginal_value_rub_per_m3(
    state: PolicyState, context: RuleContext, injector: str
) -> tuple[float, dict[str, float]]:
    influence = context.influence
    if influence is None:
        raise ValueError("R1 требует измеренную λ: без матрицы влияния ценность не считается")
    if injector not in influence.injectors:
        raise ValueError(f"{injector} отсутствует в окне применимости λ")
    column = influence.injectors.index(injector)
    density = context.oil_density_t_per_m3
    normatives = context.normatives
    gross = 0.0
    covered = 0
    for row, producer in enumerate(influence.producers):
        observation = state.wells.get(producer)
        if observation is None or observation.role is not Role.PROD:
            continue
        if not observation.is_open or observation.liquid_rate_m3_per_day <= 0.0:
            continue
        sensitivity = influence.matrix[row][column]
        watercut = observation.watercut(density)
        gross += sensitivity * oil_margin_rub_per_m3_liquid(
            normatives, density, watercut
        )
        covered += 1
    value = gross - normatives.opex_injection_rub_per_m3
    inputs = {
        "gross_value_rub_per_m3": gross,
        "opex_injection_rub_per_m3": normatives.opex_injection_rub_per_m3,
        "marginal_value_rub_per_m3": value,
        "producers_covered": float(covered),
        "oil_margin_rub_per_t": oil_margin_rub_per_t(normatives),
        "oil_density_t_per_m3": density,
        "lambda_lag_months": float(influence.lag_months),
    }
    return value, inputs


def held_target(
    baseline: Mapping[str, float],
    caps: Mapping[str, float],
    well: str,
) -> float:
    target = max(0.0, float(baseline.get(well, 0.0)))
    cap = caps.get(well)
    if cap is None:
        return target
    ceiling = float(cap)
    if ceiling < 0.0:
        raise ValueError(
            f"{well}: отрицательный потолок приёмистости {ceiling} м³/сут"
        )
    return min(target, ceiling)


def apply(state: PolicyState, context: RuleContext, theta: Theta) -> RuleOutcome:
    lag_months = read(theta, "r1_lag_months")
    budget = context.injection_budget_m3_per_day
    if budget is None:
        raise ValueError(
            "R1 требует лимит закачки от менеджера месторождения: "
            "распределять нечего, пока фонд воды не выдан"
        )
    influence = context.influence
    if influence is None:
        raise ValueError(
            "R1 требует измеренную λ: без матрицы влияния предельная ценность "
            "закачки не определена"
        )
    injectors = tuple(
        well for well in state.injectors() if well in influence.injectors
    )
    unmeasured = tuple(
        well for well in state.injectors() if well not in influence.injectors
    )
    if not injectors and not unmeasured:
        return RuleOutcome(decisions=(), trace=())

    values: dict[str, float] = {}
    inputs_by_well: dict[str, dict[str, float]] = {}
    for injector in injectors:
        value, inputs = marginal_value_rub_per_m3(state, context, injector)
        values[injector] = value
        inputs_by_well[injector] = inputs

    baseline = context.baseline_injection_m3_per_day
    caps = context.injection_cap_m3_per_day
    held_by_well = {
        well: held_target(baseline, caps, well) for well in unmeasured
    }
    held = float(sum(held_by_well.values()))
    budget_for_measured = max(0.0, budget - held)

    ranked = sorted(
        (well for well in injectors if values[well] > 0.0),
        key=lambda well: (-values[well], well),
    )
    allocation: dict[str, float] = {}
    remaining = budget_for_measured
    for well in ranked:
        if remaining <= 0.0:
            break
        cap = float(caps.get(well, remaining))
        target = min(cap, remaining)
        if target <= 0.0:
            continue
        allocation[well] = target
        remaining -= target
    decisions: list[ControlEvent] = []
    trace: list[TraceEntry] = []
    for injector in injectors:
        value = values[injector]
        target = allocation.get(injector, 0.0)
        share = target / budget_for_measured if budget_for_measured > 0.0 else 0.0
        decision = "SET_RATE"
        decisions.append(
            ControlEvent(
                control_step=state.control_step,
                well=injector,
                kind=EventKind.SET_RATE,
                value=target,
            )
        )
        entry_inputs = dict(inputs_by_well[injector])
        entry_inputs.update(
            {
                "theta_r1_lag_months": lag_months,
                "injection_budget_m3_per_day": budget,
                "budget_held_outside_lambda_m3_per_day": held,
                "budget_for_measured_m3_per_day": budget_for_measured,
                "injection_cap_m3_per_day": float(caps.get(injector, 0.0)),
                "budget_unallocated_m3_per_day": float(remaining),
                "share_of_budget": share,
                "target_rate_m3_per_day": target,
                "previous_setpoint_m3_per_day": state.wells[injector].setpoint_m3_per_day,
            }
        )
        trace.append(
            TraceEntry(
                control_step=state.control_step,
                well=injector,
                rule=RULE,
                inputs=entry_inputs,
                decision=decision,
            )
        )

    for injector in unmeasured:
        requested = max(0.0, float(baseline.get(injector, 0.0)))
        target = held_by_well[injector]
        capped = target < requested
        cap = caps.get(injector)
        decisions.append(
            ControlEvent(
                control_step=state.control_step,
                well=injector,
                kind=EventKind.SET_RATE,
                value=target,
            )
        )
        trace.append(
            TraceEntry(
                control_step=state.control_step,
                well=injector,
                rule=RULE,
                inputs={
                    "target_rate_m3_per_day": target,
                    "baseline_rate_m3_per_day": requested,
                    "injection_cap_m3_per_day": (
                        float(cap) if cap is not None else requested
                    ),
                    "capped_by_injectivity": float(capped),
                    "previous_setpoint_m3_per_day": state.wells[
                        injector
                    ].setpoint_m3_per_day,
                    "outside_lambda_window": 1.0,
                    "producers_covered": 0.0,
                },
                decision=(
                    "HOLD_BASELINE_CAPPED_OUTSIDE_LAMBDA"
                    if capped
                    else "HOLD_BASELINE_OUTSIDE_LAMBDA"
                ),
            )
        )
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))
