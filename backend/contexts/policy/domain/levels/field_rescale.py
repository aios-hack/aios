from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from backend.contexts.policy.domain.policy import TraceEntry
from backend.contexts.policy.domain.state import PolicyState
from backend.contexts.schedule.domain.schedule import ControlEvent, EventKind, Role

def _requested_injection(
    events: Sequence[ControlEvent], state: PolicyState, wells: Sequence[str]
) -> float:
    inside = set(wells)
    latest: dict[str, float] = {}
    for event in events:
        if event.kind is not EventKind.SET_RATE or event.value is None:
            continue
        if event.well not in inside:
            continue
        latest[event.well] = event.value
    untouched = 0.0
    for well in inside:
        if well in latest:
            continue
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.INJ:
            continue
        if not observation.is_open:
            continue
        untouched += observation.injection_rate_m3_per_day
    return sum(latest.values()) + untouched


def _untouched_injectors(
    events: Sequence[ControlEvent], state: PolicyState, wells: Sequence[str]
) -> tuple[str, ...]:
    touched = {
        event.well
        for event in events
        if event.kind is EventKind.SET_RATE and event.value is not None
    }
    return tuple(
        well
        for well in sorted(wells)
        if well not in touched
        and well in state.wells
        and state.wells[well].role is Role.INJ
        and state.wells[well].is_open
        and state.wells[well].injection_rate_m3_per_day > 0.0
    )


def _requested_liquid(
    events: Sequence[ControlEvent], state: PolicyState, wells: Sequence[str]
) -> float:
    inside = set(wells)
    latest: dict[str, float] = {}
    for event in events:
        if event.kind is not EventKind.SET_LRAT or event.value is None:
            continue
        if event.well not in inside:
            continue
        latest[event.well] = event.value
    untouched = 0.0
    for well in inside:
        if well in latest:
            continue
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.PROD:
            continue
        if not observation.is_open:
            continue
        untouched += observation.liquid_rate_m3_per_day
    return sum(latest.values()) + untouched


def _untouched_producers(
    events: Sequence[ControlEvent], state: PolicyState, wells: Sequence[str]
) -> tuple[str, ...]:
    touched = {
        event.well
        for event in events
        if event.kind is EventKind.SET_LRAT and event.value is not None
    }
    return tuple(
        well
        for well in sorted(wells)
        if well not in touched
        and well in state.wells
        and state.wells[well].role is Role.PROD
        and state.wells[well].is_open
        and state.wells[well].liquid_rate_m3_per_day > 0.0
    )


def _scale_liquid_event(event: ControlEvent, factor: float) -> ControlEvent:
    if event.kind is not EventKind.SET_LRAT or event.value is None:
        return event
    return replace(event, value=event.value * factor)


def _scale_liquid_entry(entry: TraceEntry, factor: float) -> TraceEntry:
    if entry.decision != "SET_LRAT":
        return entry
    inputs = dict(entry.inputs)
    inputs["group_liquid_limit_scale"] = factor
    if "target_rate_m3_per_day" in inputs:
        inputs["target_rate_m3_per_day"] = inputs["target_rate_m3_per_day"] * factor
    return replace(entry, inputs=inputs)


def _scale_event(event: ControlEvent, factor: float) -> ControlEvent:
    if event.kind is not EventKind.SET_RATE or event.value is None:
        return event
    return replace(event, value=event.value * factor)


def _scale_entry(entry: TraceEntry, factor: float) -> TraceEntry:
    inputs = dict(entry.inputs)
    inputs["group_limit_scale"] = factor
    if "target_rate_m3_per_day" in inputs:
        inputs["target_rate_m3_per_day"] = inputs["target_rate_m3_per_day"] * factor
    return replace(entry, inputs=inputs)
