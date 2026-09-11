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
from backend.core.contracts import (
    Schedule,
    EventKind,
)
from backend.domain.schedule import (
    canonicalize,
)


def _lambda_connectivity(lambda_) -> dict[str, float]:
    if lambda_ is None:
        raise ConnectivitySearchError(
            "λ не загружена: ранжировать закачку по связности нечем, а перебор "
            "по номеру скважины оптимизирует не то, что заявлено"
        )
    injectors = tuple(lambda_.injectors)
    if not injectors:
        raise ConnectivitySearchError(
            "λ не содержит ни одной нагнетательной: ранжировать закачку по "
            "связности нечем, а перебор по номеру скважины оптимизирует не то, "
            "что заявлено"
        )
    strength: dict[str, float] = {}
    for column, injector in enumerate(injectors):
        total = 0.0
        for row in lambda_.matrix:
            value = float(row[column])
            if not math.isfinite(value):
                raise ConnectivitySearchError(
                    f"λ содержит нечисловой коэффициент для нагнетательной "
                    f"{injector}: предельная ценность закачки не определена"
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
            f"в исходном плане закачка задана {len(active)} нагнетательным из "
            f"{len(strength)} в окне λ: перераспределять закачку между "
            "соседями не между кем"
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
            "ни одной пары «донор — получатель» с положительным перепадом "
            "связности и ненулевой закачкой: перераспределение по λ не "
            "строится, а слепой перебор по номеру скважины подставлять запрещено"
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
