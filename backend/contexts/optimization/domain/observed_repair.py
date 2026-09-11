from dataclasses import replace
import math

from backend.core.contracts import ControlEvent, EventKind, water_supply_policy
from backend.contexts.constraints.domain.constraints import bhp_limits
from backend.domain.schedule import canonicalize


def production_from_observation(schedule, response, constraints, *, scale=1.25, pressure_margin=10.0):
    from backend.contexts.reservoir.domain.horizon import HORIZON
    if not math.isfinite(scale) or scale <= 1 or not math.isfinite(pressure_margin) or pressure_margin < 0:
        raise ValueError("scale must exceed 1 and pressure margin must be nonnegative and finite")
    states = {(s.deck_date_index - HORIZON.history_offset - 1, s.well): s for s in response.state_at_date}
    threshold = bhp_limits(constraints).producer_min_bar + pressure_margin
    events = []
    for event in schedule.control_events:
        state = states.get((event.control_step, event.well))
        if (event.kind is EventKind.SET_LRAT and event.value > 0 and state is not None
                and state.bhp > threshold and state.liquid_rate >= 0.95 * event.value):
            event = replace(event, value=min(500.0, event.value * scale))
        events.append(event)
    return canonicalize(replace(schedule, control_events=tuple(events)))


def commissioning_controls(schedule):
    events = list(schedule.control_events)
    present = {(e.control_step, e.well, e.kind) for e in events}
    for fixed in schedule.fixed_deck_events:
        if fixed.control_step >= schedule.meta.n_intervals:
            continue
        if fixed.operator == "WCONINJE":
            kind, value, status = EventKind.SET_RATE, float(fixed.raw_args[3]), fixed.raw_args[1]
        elif fixed.operator == "WCONPROD":
            kind, value, status = EventKind.SET_LRAT, float(fixed.raw_args[5]), fixed.raw_args[0]
        else:
            continue
        key = (fixed.control_step, fixed.well)
        if (*key, kind) not in present:
            events.append(ControlEvent(*key, kind, value))
            present.add((*key, kind))
        if not any((*key, k) in present for k in (EventKind.OPEN, EventKind.SHUT)):
            status_kind = EventKind[status]
            events.append(ControlEvent(*key, status_kind))
            present.add((*key, status_kind))
    return canonicalize(replace(schedule, control_events=tuple(events)))


def repair_from_observation(schedule, response, control_dates, constraints, *, water_margin=0.8, density=0.9131, injection_reference=None):
    if not 0 <= water_margin < 1 or density <= 0:
        raise ValueError("water margin must be in [0,1), density must be positive")
    schedule = commissioning_controls(schedule)
    if injection_reference is not None:
        injection_reference = commissioning_controls(injection_reference)
        reference = {(e.control_step, e.well, e.kind): e for e in injection_reference.control_events}
        injectors = {(e.control_step, e.well) for e in injection_reference.control_events if e.kind is EventKind.SET_RATE}
        statuses = {(e.control_step, e.well): e for e in injection_reference.control_events
                    if e.kind in (EventKind.OPEN, EventKind.SHUT)}
        restored = []
        for event in schedule.control_events:
            key = (event.control_step, event.well)
            if event.kind is EventKind.SET_RATE:
                event = reference.get((*key, event.kind), event)
            elif key in injectors and event.kind in (EventKind.OPEN, EventKind.SHUT):
                event = statuses.get(key, event)
            restored.append(event)
        schedule = replace(schedule, control_events=tuple(restored))
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
    if water_margin == 0:
        factors = {step: 0.0 for step in targets}
    elif policy.enabled:
        for step, target in targets.items():
            days = (control_dates[step + 1] - control_dates[step]).days
            available = policy.external_water_m3_per_day + float(policy.reinjection_fraction or 0) * water.get(step - policy.lag_steps, 0.0) / days
            factors[step] = min(1.0, water_margin * available / target) if target > 0 else 1.0
    from backend.contexts.reservoir.domain.horizon import HORIZON
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
    injection_keys = {(e.control_step, e.well) for e in schedule.control_events if e.kind is EventKind.SET_RATE}
    for event in schedule.control_events:
        if event.value is not None:
            factor = factors.get(event.control_step, 1.0) if event.kind is EventKind.SET_RATE else 1.0
            factor *= pressure_factors.get((event.control_step, event.well, event.kind), 1.0)
            event = replace(event, value=event.value * factor)
        if water_margin == 0 and event.kind is EventKind.OPEN and (event.control_step, event.well) in injection_keys:
            event = replace(event, kind=EventKind.SHUT)
        events.append(event)
    return canonicalize(replace(schedule, control_events=tuple(events)))
