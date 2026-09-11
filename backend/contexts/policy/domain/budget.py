from __future__ import annotations

from datetime import date
from typing import Sequence

from backend.core.contracts import (
    Constraints,
    ControlEvent,
    EventKind,
    N_INTERVALS,
    OperatingStatus,
    ResponseArtifact,
    Schedule,
)


def liquid_limit_for_step(
    constraints: Constraints,
    year: int,
    control_step: int,
) -> float | None:
    if not (0 <= control_step <= N_INTERVALS - 1):
        raise ValueError(
            f"control_step={control_step} вне 0…{N_INTERVALS - 1}: "
            f"суточной ставки отбора на этом шаге не существует"
        )
    limit = constraints.liquid_limits.get(year)
    if limit is None:
        return None
    value = float(limit)
    if value < 0.0:
        raise ValueError(
            f"лимит жидкости на {year} год отрицателен: {value} м³/сут"
        )
    return value


def production_floor_for_step(
    constraints: Constraints,
    year: int,
    control_step: int,
) -> float | None:
    if not (0 <= control_step <= N_INTERVALS - 1):
        raise ValueError(
            f"control_step={control_step} вне 0…{N_INTERVALS - 1}: "
            f"суточной ставки добычи на этом шаге не существует"
        )
    floor = constraints.production_floors.get(year)
    if floor is None:
        return None
    value = float(floor)
    if value < 0.0:
        raise ValueError(
            f"нижняя граница добычи нефти на {year} год отрицательна: "
            f"{value} т/сут"
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
                f"потолок закачки скважины отрицателен: {value} м³/сут"
            )
        candidates.append(value)
    if field_budget_m3_per_day is not None:
        value = float(field_budget_m3_per_day)
        if value < 0.0:
            raise ValueError(
                f"водный бюджет поля отрицателен: {value} м³/сут"
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
        raise ValueError("плотность нефти должна быть положительной")
    if not (0 <= control_step <= N_INTERVALS - 1):
        raise ValueError(
            f"control_step={control_step} вне 0…{N_INTERVALS - 1}: "
            f"суточной ставки попутной воды на этом шаге не существует"
        )
    if control_step + 1 >= len(control_dates):
        raise ValueError(
            f"control_step={control_step}: в оси управляющих дат "
            f"{len(control_dates)} значений, правая граница интервала "
            f"не читается — длину интервала вывести не из чего"
        )
    days = (control_dates[control_step + 1] - control_dates[control_step]).days
    if days <= 0:
        raise ValueError(
            f"control_step={control_step}: неположительная длина интервала"
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
