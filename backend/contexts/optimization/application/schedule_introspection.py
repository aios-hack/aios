from __future__ import annotations


from backend.contexts.optimization.domain.injection_budget import (
    PHYSICAL_HEADROOM,
    Projection,
    admit_candidate,
)
from backend.contexts.optimization.domain.errors import (
    ScheduleSearchError,
)
from dataclasses import dataclass, replace
from typing import (
    Mapping,
    Sequence,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.schedule import (
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
)
from backend.contexts.connectivity.domain.connectivity import Groups
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.policy.domain.agents.projection import (
    HardConstraints,
    project_to_hard_constraints,
)
from backend.contexts.policy.application.hierarchy import observations_by_group
from backend.contexts.policy.domain.memory import PolicyMemory, esp_size_for
from backend.contexts.policy.domain.rules import r3
from backend.contexts.policy.domain.state import PolicyState, RuleContext, WellObservation
from backend.contexts.reservoir.domain.horizon import HORIZON


_HISTORY_DECK_OFFSET = HORIZON.history_offset

@dataclass(frozen=True, slots=True)
class PolicyFeedback:
    response: ResponseArtifact
    schedule: Schedule


def _commission_steps(schedule: Schedule) -> dict[str, int]:
    steps: dict[str, int] = {}
    for well, state in schedule.initial_state.items():
        if state.role is not Role.NONE:
            steps[well] = 0
    for event in schedule.fixed_deck_events:
        if event.operator in ("WCONPROD", "WCONINJE"):
            steps.setdefault(event.well, event.control_step)
    return steps


def _flow_start_steps(
    schedule: Schedule,
    initial_rates: Mapping[str, tuple[float, float, float]] | None = None,
) -> dict[str, int]:
    commissioned = _commission_steps(schedule)
    first_completion: dict[str, int] = {}
    for event in schedule.fixed_deck_events:
        if event.operator not in ("COMPDAT", "COMPDATMD"):
            continue
        first_completion[event.well] = min(
            event.control_step,
            first_completion.get(event.well, event.control_step),
        )
    result: dict[str, int] = {}
    for well, step in commissioned.items():
        initial = schedule.initial_state.get(well)
        initial_rate = (initial_rates or {}).get(well, (0.0, 0.0, 0.0))
        contradictory_open = (
            initial is not None
            and initial.role is not Role.NONE
            and initial.operating_status is OperatingStatus.OPEN
            and initial.setpoint > 0.0
            and max(initial_rate[0], initial_rate[2]) <= 0.0
            and well in first_completion
        )
        if (
            initial is not None
            and initial.role is not Role.NONE
            and not contradictory_open
        ):
            result[well] = 0
            continue
        result[well] = max(step, first_completion.get(well, step))
    return result


def _role_at_commission(schedule: Schedule) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for well, state in schedule.initial_state.items():
        if state.role is not Role.NONE:
            roles[well] = state.role
    for event in schedule.fixed_deck_events:
        if event.operator == "WCONPROD":
            roles.setdefault(event.well, Role.PROD)
        elif event.operator == "WCONINJE":
            roles.setdefault(event.well, Role.INJ)
    return roles


def _rates_at(
    response: ResponseArtifact, deck_date_index: int
) -> dict[str, tuple[float, float, float]]:
    return {
        item.well: (item.liquid_rate, item.oil_rate, item.injection_rate)
        for item in response.state_at_date
        if item.deck_date_index == deck_date_index
    }


def _build_policy_state(
    control_step: int,
    response: ResponseArtifact,
    *,
    wells: tuple[str, ...],
    current_role: Mapping[str, Role],
    current_is_open: Mapping[str, bool],
    current_setpoint: Mapping[str, float],
    commission_step: Mapping[str, int],
    oil_density_t_per_m3: float,
) -> PolicyState:
    rates = _rates_at(response, _HISTORY_DECK_OFFSET + control_step)
    observations: dict[str, WellObservation] = {}
    for well in wells:
        if control_step < commission_step.get(well, 0):
            continue
        role = current_role[well]
        if role is Role.NONE:
            continue
        liquid, oil, injection = rates.get(well, (0.0, 0.0, 0.0))
        liquid = max(liquid, 0.0)
        oil = max(0.0, min(oil, liquid * oil_density_t_per_m3 * (1.0 - 1e-9)))
        observations[well] = WellObservation(
            well=well,
            role=role,
            is_open=current_is_open[well],
            liquid_rate_m3_per_day=liquid,
            oil_rate_t_per_day=oil,
            injection_rate_m3_per_day=max(injection, 0.0),
            setpoint_m3_per_day=current_setpoint[well],
        )
    return PolicyState(control_step=control_step, wells=observations)


def _group_injection_offtake(
    state: PolicyState, groups: Groups
) -> tuple[dict[str, float], dict[str, float]]:
    by_group = observations_by_group(state, groups)
    injection: dict[str, float] = {}
    offtake: dict[str, float] = {}
    for group_id, wells in by_group.items():
        injection[group_id] = sum(
            w.injection_rate_m3_per_day for w in wells if w.role is Role.INJ and w.is_open
        )
        offtake[group_id] = sum(
            w.liquid_rate_m3_per_day for w in wells if w.role is Role.PROD and w.is_open
        )
    return injection, offtake


def _apply_decision(
    event: ControlEvent,
    *,
    current_role: dict[str, Role],
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
    memory: PolicyMemory,
) -> PolicyMemory:
    if event.kind is EventKind.OPEN:
        current_is_open[event.well] = True
    elif event.kind is EventKind.SHUT:
        current_is_open[event.well] = False
    elif event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
        current_setpoint[event.well] = event.value if event.value is not None else 0.0
    elif event.kind is EventKind.CONVERT_INJ:
        current_role[event.well] = Role.INJ
        current_is_open[event.well] = True
        memory = memory.updated(
            event.well, memory.of(event.well).converted_at(event.control_step)
        )
    return memory


def _advance_memory(state: PolicyState, context: RuleContext, *, esp_catalog) -> PolicyMemory:
    memory = context.memory
    for well, observation in state.wells.items():
        current = memory.of(well)
        if observation.role is Role.PROD:
            current = r3.advance(state, replace(context, memory=memory), well)
        if observation.liquid_rate_m3_per_day > 0.0:
            needed = esp_size_for(esp_catalog, observation.liquid_rate_m3_per_day)
            if needed.nominal > current.esp_nominal_m3_per_day:
                current = current.with_esp(needed.nominal)
        memory = memory.updated(well, current)
    return memory


def _physical_caps(schedule: Schedule) -> tuple[dict[str, float], float]:
    per_well: dict[str, float] = {}
    by_step_injection: dict[int, float] = {}
    for event in schedule.control_events:
        if event.value is None or event.value <= 0.0:
            continue
        if event.kind not in (EventKind.SET_RATE, EventKind.SET_LRAT):
            continue
        previous = per_well.get(event.well, 0.0)
        per_well[event.well] = max(previous, event.value * PHYSICAL_HEADROOM)
        if event.kind is EventKind.SET_RATE:
            by_step_injection[event.control_step] = (
                by_step_injection.get(event.control_step, 0.0) + event.value
            )
    field_limit = max(by_step_injection.values(), default=0.0) * PHYSICAL_HEADROOM
    if field_limit <= 0.0:
        raise ScheduleSearchError(
            "the baseline schedule has no positive injection setpoint: there is "
            "nothing to derive the physical field ceiling from"
        )
    return per_well, field_limit


def _active_outage_wells(
    constraints: Constraints, control_step: int
) -> frozenset[str]:
    return frozenset(
        outage.well
        for outage in constraints.well_outages
        if outage.control_step_from <= control_step <= outage.control_step_to
    )


def _outage_events(
    state: PolicyState, wells: frozenset[str]
) -> tuple[ControlEvent, ...]:
    events: list[ControlEvent] = []
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None:
            continue
        target_kind = (
            EventKind.SET_RATE
            if observation.role is Role.INJ
            else EventKind.SET_LRAT
        )
        events.extend(
            (
                ControlEvent(
                    control_step=state.control_step,
                    well=well,
                    kind=target_kind,
                    value=0.0,
                ),
                ControlEvent(
                    control_step=state.control_step,
                    well=well,
                    kind=EventKind.SHUT,
                ),
            )
        )
    return tuple(events)


def _baseline_conversion_steps(schedule: Schedule) -> dict[str, int]:
    steps: dict[str, int] = {}
    for event in schedule.control_events:
        if event.kind is EventKind.CONVERT_INJ:
            previous = steps.get(event.well)
            if previous is None or event.control_step < previous:
                steps[event.well] = event.control_step
    return steps


def _emit_dense_layer(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    state: PolicyState,
    *,
    current_role: dict[str, Role],
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
    hard: HardConstraints,
    projection: Projection = project_to_hard_constraints,
) -> None:
    for well in state.wells:
        role = current_role.get(well, Role.PROD)
        target_kind = EventKind.SET_RATE if role is Role.INJ else EventKind.SET_LRAT
        if (step, well, target_kind) not in pending:
            admit_candidate(
                pending,
                ControlEvent(
                    control_step=step,
                    well=well,
                    kind=target_kind,
                    value=current_setpoint.get(well, 0.0),
                ),
                hard,
                projection,
            )
        status_kind = EventKind.OPEN if current_is_open.get(well, False) else EventKind.SHUT
        other = EventKind.SHUT if status_kind is EventKind.OPEN else EventKind.OPEN
        pending.pop((step, well, other), None)
        if (step, well, status_kind) not in pending:
            admit_candidate(
                pending,
                ControlEvent(
                    control_step=step, well=well, kind=status_kind, value=None
                ),
                hard,
                projection,
            )


def _close_producing_side_on_conversion(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    decisions: Sequence[ControlEvent],
    hard: HardConstraints,
    projection: Projection = project_to_hard_constraints,
) -> None:
    converted = {
        event.well for event in decisions if event.kind is EventKind.CONVERT_INJ
    }
    for well in converted:
        key = (step, well, EventKind.SET_LRAT)
        event = pending.get(key)
        if event is not None and event.value:
            admit_candidate(pending, replace(event, value=0.0), hard, projection)

