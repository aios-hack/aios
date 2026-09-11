from __future__ import annotations

from datetime import date
from typing import Sequence

from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.schedule import (
    ControlEvent,
    EventKind,
    N_INTERVALS,
    OperatingStatus,
    Schedule,
)
from backend.contexts.runs.domain.run_result import ResponseArtifact


def liquid_limit_for_step(
    constraints: Constraints,
    year: int,
    control_step: int,
) -> float | None:
    if not (0 <= control_step <= N_INTERVALS - 1):
        raise ValueError(
            f"control_step={control_step} is outside 0…{N_INTERVALS - 1}: "
            f"no daily offtake rate exists at this step"
        )
    limit = constraints.liquid_limits.get(year)
    if limit is None:
        return None
    value = float(limit)
    if value < 0.0:
        raise ValueError(
            f"the liquid limit for the year {year} is negative: {value} m3/day"
        )
    return value


def production_floor_for_step(
    constraints: Constraints,
    year: int,
    control_step: int,
) -> float | None:
    if not (0 <= control_step <= N_INTERVALS - 1):
        raise ValueError(
            f"control_step={control_step} is outside 0…{N_INTERVALS - 1}: "
            f"no daily production rate exists at this step"
        )
    floor = constraints.production_floors.get(year)
    if floor is None:
        return None
    value = float(floor)
    if value < 0.0:
        raise ValueError(
            f"the lower bound on oil production for the year {year} is negative: "
            f"{value} t/day"
        )
    return value


def injection_ceiling_for_well(
    well_cap_m3_per_day: float | None,
    field_budget_m3_per_day: float | None,
) -> float | None:
    candidates: list[float] = []
    if well_cap_m3_per_day is not None:
        value = float(well_cap_m3_per_day)
        if value < 0.0:
            raise ValueError(
                f"the well injection ceiling is negative: {value} m3/day"
            )
        candidates.append(value)
    if field_budget_m3_per_day is not None:
        value = float(field_budget_m3_per_day)
        if value < 0.0:
            raise ValueError(
                f"the field water budget is negative: {value} m3/day"
            )
        candidates.append(value)
    if not candidates:
        return None
    return min(candidates)


def interval_produced_water_rate_m3_per_day(
    response: ResponseArtifact,
    control_step: int,
    control_dates: Sequence[date],
    oil_density_t_per_m3: float,
) -> float:
    if oil_density_t_per_m3 <= 0.0:
        raise ValueError("oil density must be positive")
    if not (0 <= control_step <= N_INTERVALS - 1):
        raise ValueError(
            f"control_step={control_step} is outside 0…{N_INTERVALS - 1}: "
            f"no daily produced-water rate exists at this step"
        )
    if control_step + 1 >= len(control_dates):
        raise ValueError(
            f"control_step={control_step}: the control date axis holds "
            f"{len(control_dates)} values, so the right end of the interval "
            f"cannot be read: there is nothing to derive the interval length from"
        )
    days = (control_dates[control_step + 1] - control_dates[control_step]).days
    if days <= 0:
        raise ValueError(
            f"control_step={control_step}: non-positive interval length"
        )
    water_volume = 0.0
    for item in response.interval_response:
        if item.control_step != control_step:
            continue
        oil_volume = max(0.0, item.oil_mass_delta) / oil_density_t_per_m3
        water_volume += max(0.0, item.liquid_volume_delta - oil_volume)
    return water_volume / days


def baseline_injection_by_step(
    schedule: Schedule,
) -> tuple[dict[str, float], ...]:
    current: dict[str, float] = {
        well: (
            float(state.setpoint or 0.0)
            if state.operating_status is OperatingStatus.OPEN
            else 0.0
        )
        for well, state in schedule.initial_state.items()
    }
    by_step: dict[int, list[ControlEvent]] = {}
    for event in schedule.control_events:
        by_step.setdefault(event.control_step, []).append(event)

    dense: list[dict[str, float]] = []
    for step in range(schedule.meta.n_intervals):
        for event in by_step.get(step, ()):
            if event.kind is EventKind.SET_RATE:
                current[event.well] = float(event.value or 0.0)
            elif event.kind is EventKind.SHUT:
                current[event.well] = 0.0
        dense.append(dict(current))
    return tuple(dense)
