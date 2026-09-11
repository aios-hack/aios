from __future__ import annotations

from typing import (
    Sequence,
)
from backend.contexts.schedule.domain.schedule import ControlEvent, EventKind, Role
from backend.contexts.policy.domain.state import (
    PolicyState,
    RuleContext,
)


def binding_watercut_limit(context: RuleContext) -> float | None:
    limits = context.constraints.watercut_limits
    if not limits:
        return None
    return min(float(value) for value in limits.values())


def _effective_liquid(
    events: Sequence[ControlEvent], state: PolicyState, well: str
) -> float:
    observation = state.wells[well]
    liquid = observation.liquid_rate_m3_per_day
    for event in events:
        if event.well != well:
            continue
        if event.kind is EventKind.SHUT:
            return 0.0
        if event.kind is EventKind.SET_LRAT and event.value is not None:
            liquid = event.value
    return liquid


def _shut_wells(events: Sequence[ControlEvent]) -> frozenset[str]:
    return frozenset(
        event.well for event in events if event.kind is EventKind.SHUT
    )


def watercut_cap_shutins(
    state: PolicyState,
    context: RuleContext,
    events: Sequence[ControlEvent],
    wells: Sequence[str],
    limit: float,
) -> tuple[tuple[str, ...], float, float]:
    density = context.oil_density_t_per_m3
    already_shut = _shut_wells(events)
    candidates: list[tuple[float, str, float, float]] = []
    oil_total = 0.0
    liquid_total = 0.0
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.PROD:
            continue
        if not observation.is_open or well in already_shut:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        liquid = _effective_liquid(events, state, well)
        if liquid <= 0.0:
            continue
        share = liquid / observation.liquid_rate_m3_per_day
        oil_volume = (
            observation.oil_rate_t_per_day / density
        ) * share
        oil_total += oil_volume
        liquid_total += liquid
        candidates.append(
            (observation.watercut(density), well, liquid, oil_volume)
        )
    if liquid_total <= 0.0:
        return (), 0.0, 0.0
    before = 1.0 - oil_total / liquid_total
    if before <= limit:
        return (), before, before
    ordered = sorted(candidates, key=lambda item: (-item[0], item[1]))
    shut: list[str] = []
    current = before
    for _watercut, well, liquid, oil_volume in ordered:
        if current <= limit:
            break
        liquid_total -= liquid
        oil_total -= oil_volume
        shut.append(well)
        if liquid_total <= 0.0:
            current = 0.0
            break
        current = 1.0 - oil_total / liquid_total
    if current > limit:
        raise ValueError(
            f"the watercut ceiling {limit} is unreachable by shut-ins: "
            f"the group is left at {current}"
        )
    return tuple(shut), before, current


__all__ = [
    "binding_watercut_limit",
    "watercut_cap_shutins",
]
