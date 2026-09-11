from __future__ import annotations

from backend.contexts.optimization.application.search_config import (
    WATER_REPAIR_CEILING,
    WATER_REPAIR_MARGIN,
)
import math
from dataclasses import (
    replace,
)
from backend.contexts.schedule.domain.schedule import EventKind, Schedule
from backend.contexts.constraints.domain.constraints import water_supply_policy
from backend.contexts.optimization.domain.injection_budget import (
    SOURCE_WATER_BALANCE_REPAIR,
)
from backend.contexts.schedule.domain.validate import ViolationKind
from backend.contexts.schedule.domain.canonical import canonicalize
from backend.contexts.schedule.domain.validate_dynamic import validate_dynamic


def _repair_predicted_water_balance(
    env,
    evaluator,
    schedule: Schedule,
    rounds: int = 8,
    budget_trace: list[dict[str, object]] | None = None,
):
    policy = water_supply_policy(env.constraints)
    if not policy.enabled:
        evaluated = evaluator(schedule)
        response = evaluated.state.response
        dynamic = validate_dynamic(
            schedule,
            response.state_at_date,
            response.interval_response,
            env.constraints,
            env.oil_density_t_per_m3,
            groups=env.groups,
        )
        return schedule, evaluated, dynamic, 0

    current = schedule
    for round_index in range(rounds + 1):
        evaluated = evaluator(current)
        response = evaluated.state.response
        dynamic = validate_dynamic(
            current,
            response.state_at_date,
            response.interval_response,
            env.constraints,
            env.oil_density_t_per_m3,
            groups=env.groups,
        )
        bad_steps = {
            item.control_step
            for item in dynamic.violations
            if item.kind is ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED
            and item.control_step is not None
        }
        if not bad_steps or round_index == rounds:
            return current, evaluated, dynamic, round_index

        produced_water: dict[int, float] = {}
        injected: dict[int, float] = {}
        for item in response.interval_response:
            oil_volume = max(0.0, item.oil_mass_delta) / env.oil_density_t_per_m3
            produced_water[item.control_step] = produced_water.get(item.control_step, 0.0) + max(
                0.0, item.liquid_volume_delta - oil_volume
            )
            injected[item.control_step] = injected.get(item.control_step, 0.0) + max(
                0.0, item.injection_volume_delta
            )
        factors: dict[int, float] = {}
        for step in bad_steps:
            source_step = step - policy.lag_steps
            days = (env.control_dates[step + 1] - env.control_dates[step]).days
            available = (
                policy.external_water_m3_per_day * days
                + float(policy.reinjection_fraction or 0.0)
                * produced_water.get(source_step, 0.0)
            )
            actual = injected.get(step, 0.0)
            factors[step] = (
                0.0
                if actual <= 0.0
                else min(
                    WATER_REPAIR_CEILING, WATER_REPAIR_MARGIN * available / actual
                )
            )
            if budget_trace is not None:
                budget_trace.append(
                    {
                        "control_step": step,
                        "round": round_index,
                        "binding_source": SOURCE_WATER_BALANCE_REPAIR,
                        "limit_m3": available * WATER_REPAIR_MARGIN,
                        "contributions": {
                            "available_m3": available,
                            "commanded_m3": actual,
                            "repair_margin": WATER_REPAIR_MARGIN,
                            "repair_ceiling": WATER_REPAIR_CEILING,
                            "factor": factors[step],
                        },
                    }
                )

        values: dict[tuple[int, str], float] = {}
        repaired = []
        for event in current.control_events:
            if event.kind is EventKind.SET_RATE and event.control_step in factors:
                value = math.floor(float(event.value or 0.0) * factors[event.control_step])
                event = replace(event, value=max(0.0, value))
                values[(event.control_step, event.well)] = float(event.value or 0.0)
            repaired.append(event)
        normalized = []
        for event in repaired:
            value = values.get((event.control_step, event.well))
            if value is not None and event.kind in (EventKind.OPEN, EventKind.SHUT):
                event = replace(
                    event,
                    kind=EventKind.OPEN if value > 0.0 else EventKind.SHUT,
                )
            normalized.append(event)
        current = canonicalize(replace(current, control_events=tuple(normalized)))
    raise AssertionError("unreachable")
