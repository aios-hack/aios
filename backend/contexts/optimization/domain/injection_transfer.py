from __future__ import annotations

from backend.contexts.optimization.domain.search_limits import (
    INJECTION_TRANSFER_STEPS_M3_PER_DAY,
)

from backend.contexts.optimization.domain.errors import (
    ConnectivitySearchError,
)
import math
from dataclasses import (
    replace,
)
from typing import (
    Mapping,
)
from backend.contexts.schedule.domain.schedule import EventKind, Schedule
from backend.contexts.schedule.domain.canonical import canonicalize


def _lambda_connectivity(lambda_) -> dict[str, float]:
    if lambda_ is None:
        raise ConnectivitySearchError(
            "λ is not loaded: there is nothing to rank injection by connectivity "
            "with, and enumerating by well number optimizes something other "
            "than what is declared"
        )
    injectors = tuple(lambda_.injectors)
    if not injectors:
        raise ConnectivitySearchError(
            "λ contains no injector: there is nothing to rank injection by "
            "connectivity with, and enumerating by well number optimizes "
            "something other than what is declared"
        )
    strength: dict[str, float] = {}
    for column, injector in enumerate(injectors):
        total = 0.0
        for row in lambda_.matrix:
            value = float(row[column])
            if not math.isfinite(value):
                raise ConnectivitySearchError(
                    f"λ contains a non-numeric coefficient for injector "
                    f"{injector}: the marginal value of injection is undefined"
                )
            total += value
        strength[injector] = total
    return strength


def _connectivity_groups(strength: Mapping[str, float]) -> dict[str, str]:
    ordered = sorted(strength, key=lambda well: (-strength[well], well))
    size = max(1, len(ordered) // 3)
    groups: dict[str, str] = {}
    for position, well in enumerate(ordered):
        if position < size:
            groups[well] = "high"
        elif position < 2 * size:
            groups[well] = "medium"
        else:
            groups[well] = "low"
    return groups


def _baseline_injection_rates(schedule: Schedule) -> dict[str, float]:
    rates: dict[str, float] = {}
    for event in schedule.control_events:
        if event.kind is not EventKind.SET_RATE or event.value is None:
            continue
        rates[event.well] = max(rates.get(event.well, 0.0), float(event.value))
    return rates


def _injection_transfer_plan(
    lambda_, schedule: Schedule, budget: int
) -> tuple[tuple[str, str, float], ...]:
    strength = _lambda_connectivity(lambda_)
    rates = _baseline_injection_rates(schedule)
    active = {
        well: value
        for well, value in strength.items()
        if rates.get(well, 0.0) > 0.0
    }
    if len(active) < 2:
        raise ConnectivitySearchError(
            f"the source schedule sets injection for {len(active)} injectors out of "
            f"{len(strength)} in the λ window: there is nobody to redistribute "
            "injection between"
        )
    ordered = sorted(active, key=lambda well: (-active[well], well))
    pairs: list[tuple[str, str, float]] = []
    depth = len(ordered) // 2
    for step in INJECTION_TRANSFER_STEPS_M3_PER_DAY:
        for offset in range(depth):
            receiver = ordered[offset]
            donor = ordered[-1 - offset]
            if active[receiver] <= active[donor]:
                continue
            volume = min(step, rates[donor])
            if volume <= 0.0:
                continue
            pairs.append((donor, receiver, volume))
            if len(pairs) >= budget - 1:
                return tuple(pairs)
    if not pairs:
        raise ConnectivitySearchError(
            "not a single \"donor — receiver\" pair with a positive connectivity "
            "difference and non-zero injection: redistribution by λ cannot be "
            "built, and substituting a blind enumeration by well number is "
            "forbidden"
        )
    return tuple(pairs)


def _transfer_injection(
    schedule: Schedule, donor: str, receiver: str, volume: float
) -> Schedule:
    events = tuple(
        replace(event, value=max(0.0, float(event.value) - volume))
        if event.well == donor
        and event.kind is EventKind.SET_RATE
        and event.value is not None
        else (
            replace(event, value=float(event.value) + volume)
            if event.well == receiver
            and event.kind is EventKind.SET_RATE
            and event.value is not None
            else event
        )
        for event in schedule.control_events
    )
    return canonicalize(replace(schedule, control_events=events))
