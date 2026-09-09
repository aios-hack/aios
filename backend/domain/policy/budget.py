from __future__ import annotations

from backend.core.contracts import Constraints, N_INTERVALS


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
