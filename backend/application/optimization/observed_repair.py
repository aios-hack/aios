"""Generate OPM trials from measured water availability and pressure violations.

These are proposals, not feasibility guarantees: flow must be simulated again.
"""
from dataclasses import replace

from backend.core.contracts import EventKind, water_supply_policy
from backend.core.contracts.constraints import bhp_limits
from backend.domain.schedule import canonicalize


def repair_from_observation(schedule, response, control_dates, constraints, *, water_margin=0.8, density=0.9131):
    if not 0 < water_margin < 1 or density <= 0:
        raise ValueError("water margin must be in (0,1), density must be positive")
    policy = water_supply_policy(constraints)
    water = {}
    for item in response.interval_response:
        water[item.control_step] = water.get(item.control_step, 0.0) + max(
            0.0, item.liquid_volume_delta - max(0.0, item.oil_mass_delta) / density
        )
    targets = {}
    for event in schedule.control_events:
        if event.kind is EventKind.SET_RATE:
            targets[event.control_step] = targets.get(event.control_step, 0.0) + event.value
    factors = {}
    if policy.enabled:
        for step, target in targets.items():
            days = (control_dates[step + 1] - control_dates[step]).days
            available = policy.external_water_m3_per_day + float(policy.reinjection_fraction or 0) * water.get(step - policy.lag_steps, 0.0) / days
            factors[step] = min(1.0, water_margin * available / target) if target > 0 else 1.0
    from backend.core.horizon import HORIZON
    limits = bhp_limits(constraints)
    pressure_factors = {}
    for state in response.state_at_date:
        step = state.deck_date_index - HORIZON.history_offset - 1
        if not 0 <= step < schedule.meta.n_intervals:
            continue
        if state.liquid_rate > 0 and state.bhp < limits.producer_min_bar - 0.05:
            pressure_factors[(step, state.well, EventKind.SET_LRAT)] = 0.8
        if state.injection_rate > 0 and state.bhp > limits.injector_max_bar + 0.05:
            pressure_factors[(step, state.well, EventKind.SET_RATE)] = 0.8
    events = []
    for event in schedule.control_events:
        if event.value is not None:
            factor = factors.get(event.control_step, 1.0) if event.kind is EventKind.SET_RATE else 1.0
            factor *= pressure_factors.get((event.control_step, event.well, event.kind), 1.0)
            event = replace(event, value=event.value * factor)
        events.append(event)
    return canonicalize(replace(schedule, control_events=tuple(events)))
