from __future__ import annotations

from dataclasses import replace

from backend.contexts.constraints.domain.constraints import (
    field_pressure_limits,
    water_supply_policy,
)
from backend.contexts.optimization.application.schedule_introspection import (
    PolicyFeedback,
    _active_outage_wells,
    _advance_memory,
    _apply_decision,
    _baseline_conversion_steps,
    _build_policy_state,
    _close_producing_side_on_conversion,
    _commission_steps,
    _emit_dense_layer,
    _flow_start_steps,
    _group_injection_offtake,
    _HISTORY_DECK_OFFSET,
    _outage_events,
    _physical_caps,
    _rates_at,
    _role_at_commission,
)
from backend.contexts.optimization.domain.errors import ScheduleSearchError
from backend.contexts.optimization.domain.injection_budget import (
    InjectionBudget,
    Projection,
    SETPOINT_STEP_M3_PER_DAY,
    WATER_COMMAND_SAFETY_FACTOR,
    _interval_produced_water_rate_m3_per_day,
    _relax_rate_layer,
    _scale_step_injection_to_limit,
    admit_candidate,
    injection_budget_for_step,
)
from backend.contexts.optimization.domain.search_environment import SearchEnvironment
from backend.contexts.policy.application.hierarchy import run_step
from backend.contexts.policy.domain.agents import PRESSURE_REGISTRY
from backend.contexts.policy.domain.agents.projection import (
    HardConstraints,
    project_to_hard_constraints,
)
from backend.contexts.policy.domain.budget import (
    baseline_injection_by_step,
    liquid_limit_for_step,
)
from backend.contexts.policy.domain.memory import PolicyMemory
from backend.contexts.policy.domain.policy import Theta
from backend.contexts.policy.domain.state import RuleContext
from backend.contexts.policy.domain.trace import RunTrace
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.schedule.domain.canonical import canonicalize
from backend.contexts.schedule.domain.schedule import (
    ControlEvent,
    EventKind,
    N_INTERVALS,
    Role,
    Schedule,
)


def make_policy(
    env: SearchEnvironment,
    theta: Theta,
    trace_sink: dict,
    *,
    water_reference_response: ResponseArtifact | None = None,
    projection: Projection = project_to_hard_constraints,
    command_margin: float | None = None,
    symmetric_damper: bool = True,
):
    command_margin = (
        (
            WATER_COMMAND_SAFETY_FACTOR
            if water_supply_policy(env.constraints).enabled
            else 1.0
        )
        if command_margin is None
        else command_margin
    )
    wells = env.base_schedule.meta.wells
    commission_step = _commission_steps(env.base_schedule)
    flow_start_step = _flow_start_steps(
        env.base_schedule,
        _rates_at(env.real_history, _HISTORY_DECK_OFFSET),
    )
    role_at_commission = _role_at_commission(env.base_schedule)
    well_caps, field_limit = _physical_caps(env.base_schedule)
    hard_constraints = HardConstraints(well_cap_m3_per_day=well_caps)
    baseline_injection = baseline_injection_by_step(env.base_schedule)
    pressure_limits = field_pressure_limits(env.constraints)
    baseline_conversion = _baseline_conversion_steps(env.base_schedule)
    commissioning_setpoint: dict[str, float] = {}
    for event in env.base_schedule.control_events:
        if event.kind in (EventKind.SET_RATE, EventKind.SET_LRAT) and event.value:
            key = (event.well, event.control_step)
            if event.control_step == commission_step.get(event.well, -1):
                commissioning_setpoint.setdefault(event.well, event.value)

    def policy(feedback: ResponseArtifact | PolicyFeedback) -> Schedule:
        previous_schedule: Schedule | None = None
        if isinstance(feedback, PolicyFeedback):
            response = feedback.response
            previous_schedule = feedback.schedule
        else:
            response = feedback
        current_role: dict[str, Role] = dict(role_at_commission)
        current_is_open: dict[str, bool] = {
            well: env.base_schedule.initial_state[well].operating_status.value == "OPEN"
            for well in wells
        }
        current_setpoint: dict[str, float] = {
            well: env.base_schedule.initial_state[well].setpoint for well in wells
        }
        context = RuleContext(
            normatives=env.normatives,
            oil_density_t_per_m3=env.oil_density_t_per_m3,
            constraints=env.constraints,
            influence=env.lambda_,
            groups=env.groups,
            memory=PolicyMemory(),
        )
        pending: dict[tuple[int, str, EventKind], ControlEvent] = {}
        trace_entries = []
        budget_entries: list[InjectionBudget] = []
        produced_water_by_step: list[float] = []
        for step in range(N_INTERVALS):
            for well, entry in flow_start_step.items():
                if entry == step and not current_is_open.get(well, False):
                    current_is_open[well] = True
                    if well in commissioning_setpoint:
                        current_setpoint[well] = commissioning_setpoint[well]
            state = _build_policy_state(
                step,
                response,
                wells=wells,
                current_role=current_role,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                commission_step=commission_step,
                oil_density_t_per_m3=env.oil_density_t_per_m3,
            )
            produced_water_by_step.append(
                _interval_produced_water_rate_m3_per_day(
                    water_reference_response or response,
                    step,
                    env.control_dates,
                    env.oil_density_t_per_m3,
                )
            )
            if not state.wells:
                continue
            budget = injection_budget_for_step(
                control_step=step,
                constraints=env.constraints,
                year=env.control_dates[step].year,
                produced_water_by_step=produced_water_by_step,
                physical_limit_m3_per_day=field_limit,
                command_margin=command_margin,
            )
            budget_entries.append(budget)
            step_field_limit = budget.limit_m3_per_day
            step_liquid_limit = liquid_limit_for_step(
                env.constraints, env.control_dates[step].year, step
            )
            injection, offtake = _group_injection_offtake(state, env.groups)
            result = run_step(
                state,
                replace(
                    context,
                    group_injection_m3_per_day=injection,
                    group_offtake_m3_per_day=offtake,
                    baseline_injection_m3_per_day=baseline_injection[step],
                    injection_cap_m3_per_day=well_caps,
                    baseline_conversion_step=baseline_conversion,
                    pressure_floor_bar=pressure_limits.floor_bar,
                    pressure_ceiling_bar=pressure_limits.ceiling_bar,
                ),
                theta,
                env.flags,
                field_limit_m3_per_day=step_field_limit,
                field_liquid_limit_m3_per_day=step_liquid_limit,
                setpoint_step_m3_per_day=SETPOINT_STEP_M3_PER_DAY,
                registry=PRESSURE_REGISTRY,
            )
            trace_entries.extend(leveled.entry for leveled in result.trace.entries)
            outage_wells = _active_outage_wells(env.constraints, step)
            not_ready_wells = frozenset(
                well
                for well, entry in flow_start_step.items()
                if commission_step.get(well, entry) <= step < entry
            )
            blocked_wells = outage_wells | not_ready_wells
            decisions = tuple(
                event for event in result.decisions if event.well not in blocked_wells
            ) + _outage_events(state, blocked_wells)
            for event in decisions:
                event = admit_candidate(pending, event, hard_constraints, projection)
                context = replace(
                    context,
                    memory=_apply_decision(
                        event,
                        current_role=current_role,
                        current_is_open=current_is_open,
                        current_setpoint=current_setpoint,
                        memory=context.memory,
                    ),
                )
            _close_producing_side_on_conversion(
                pending, step, decisions, hard_constraints, projection
            )
            _emit_dense_layer(
                pending,
                step,
                state,
                current_role=current_role,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                hard=hard_constraints,
                projection=projection,
            )
            commanded_injection = _scale_step_injection_to_limit(
                pending,
                step,
                step_field_limit,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                hard=hard_constraints,
                projection=projection,
            )
            if commanded_injection > step_field_limit + 1.0e-9:
                raise ScheduleSearchError(
                    f"control_step={step}: injection command {commanded_injection} "
                    f"m3/day exceeds the ceiling {step_field_limit} m3/day, "
                    f"constraint {budget.binding_source}"
                )
            context = replace(
                context,
                memory=_advance_memory(state, context, esp_catalog=env.normatives.esp_catalog),
            )
        trace_sink["trace"] = RunTrace(entries=tuple(trace_entries), flags=env.flags)
        trace_sink["injection_budget"] = tuple(
            entry.as_trace_entry() for entry in budget_entries
        )
        candidate = replace(
            env.base_schedule,
            control_events=tuple(pending.values()),
            meta=replace(env.base_schedule.meta, provenance="policy-search-candidate"),
        )
        candidate = canonicalize(candidate)
        return (
            candidate
            if previous_schedule is None
            else _relax_rate_layer(
                previous_schedule, candidate, symmetric=symmetric_damper
            )
        )

    return policy


__all__ = [
    "PolicyFeedback",
    "make_policy",
]
