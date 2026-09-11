from __future__ import annotations

from collections.abc import (
    Sequence,
)
from backend.core.contracts import (
    Groups,
    IntervalResponse,
)


def _compensation_totals(
    interval_responses: Sequence[IntervalResponse],
) -> dict[int, tuple[float, float]]:
    totals: dict[int, tuple[float, float]] = {}
    for item in interval_responses:
        withdrawal, injection = totals.get(item.control_step, (0.0, 0.0))
        totals[item.control_step] = (
            withdrawal + max(0.0, item.liquid_volume_delta),
            injection + max(0.0, item.injection_volume_delta),
        )
    return totals


def _reservoir_factors_at(
    reservoir_factors: Sequence[tuple[float, float]], control_step: int
) -> tuple[float, float]:
    if control_step < 0 or control_step >= len(reservoir_factors):
        raise ValueError(
            f"пересчёт компенсации в пластовые условия запрошен на шаге "
            f"{control_step}, но пара (B_o, B_w) для него не передана: "
            f"получено {len(reservoir_factors)} пар. Считать компенсацию по "
            "коэффициентам соседнего шага значит выдать за пластовое условие "
            "число, которого никто не считал"
        )
    oil_factor, water_factor = reservoir_factors[control_step]
    if oil_factor <= 0.0 or water_factor <= 0.0:
        raise ValueError(
            f"пара объёмных коэффициентов на шаге {control_step} неположительна: "
            f"B_o = {oil_factor}, B_w = {water_factor}; объём в пластовых "
            "условиях по ним не определён"
        )
    return oil_factor, water_factor


def reservoir_step_totals(
    oil_mass_t: float,
    liquid_volume_m3: float,
    injection_volume_m3: float,
    oil_density_t_per_m3: float,
    oil_factor: float,
    water_factor: float,
) -> tuple[float, float]:
    if oil_density_t_per_m3 <= 0.0:
        raise ValueError(
            "пересчёт компенсации в пластовые условия требует положительной "
            f"плотности нефти, получено {oil_density_t_per_m3} т/м³: объём "
            "нефти в поверхностных условиях по массе не восстановить"
        )
    oil_volume = oil_mass_t / oil_density_t_per_m3
    water_volume = max(0.0, liquid_volume_m3 - oil_volume)
    withdrawal = oil_volume * oil_factor + water_volume * water_factor
    return withdrawal, injection_volume_m3 * water_factor


def _compensation_reservoir_totals(
    interval_responses: Sequence[IntervalResponse],
    reservoir_factors: Sequence[tuple[float, float]],
    oil_density_t_per_m3: float,
) -> dict[int, tuple[float, float]]:
    surface: dict[int, tuple[float, float, float]] = {}
    for item in interval_responses:
        oil, liquid, injection = surface.get(item.control_step, (0.0, 0.0, 0.0))
        surface[item.control_step] = (
            oil + max(0.0, item.oil_mass_delta),
            liquid + max(0.0, item.liquid_volume_delta),
            injection + max(0.0, item.injection_volume_delta),
        )
    totals: dict[int, tuple[float, float]] = {}
    for control_step, (oil, liquid, injection) in surface.items():
        oil_factor, water_factor = _reservoir_factors_at(
            reservoir_factors, control_step
        )
        totals[control_step] = reservoir_step_totals(
            oil, liquid, injection, oil_density_t_per_m3, oil_factor, water_factor
        )
    return totals


def _group_membership(groups: Groups) -> dict[str, tuple[str, ...]]:
    membership: dict[str, list[str]] = {}
    for group_id in sorted(groups.groups):
        for well in groups.groups[group_id]:
            membership.setdefault(well, []).append(group_id)
    return {well: tuple(ids) for well, ids in membership.items()}


def _compensation_group_totals(
    interval_responses: Sequence[IntervalResponse],
    groups: Groups,
    reservoir_factors: Sequence[tuple[float, float]] | None = None,
    oil_density_t_per_m3: float | None = None,
) -> dict[tuple[int, str], tuple[float, float]]:
    membership = _group_membership(groups)
    uncovered = sorted(
        {item.well for item in interval_responses if item.well not in membership}
    )
    if uncovered:
        raise ValueError(
            "групповая компенсация требует, чтобы каждая скважина отклика "
            f"принадлежала участку, вне участков остались: {', '.join(uncovered)}; "
            "считать C(k) по неполной нарезке значит объявить проверку "
            "выполненной там, где часть отбора и закачки не учтена"
        )
    surface: dict[tuple[int, str], tuple[float, float, float]] = {}
    for item in interval_responses:
        for group_id in membership[item.well]:
            key = (item.control_step, group_id)
            oil, liquid, injection = surface.get(key, (0.0, 0.0, 0.0))
            surface[key] = (
                oil + max(0.0, item.oil_mass_delta),
                liquid + max(0.0, item.liquid_volume_delta),
                injection + max(0.0, item.injection_volume_delta),
            )
    if reservoir_factors is None:
        return {
            key: (liquid, injection)
            for key, (_, liquid, injection) in surface.items()
        }
    if oil_density_t_per_m3 is None:
        raise ValueError(
            "пересчёт групповой компенсации в пластовые условия запрошен "
            "без плотности нефти: объём нефти в отборе не восстановить"
        )
    totals: dict[tuple[int, str], tuple[float, float]] = {}
    for key, (oil, liquid, injection) in surface.items():
        oil_factor, water_factor = _reservoir_factors_at(reservoir_factors, key[0])
        totals[key] = reservoir_step_totals(
            oil, liquid, injection, oil_density_t_per_m3, oil_factor, water_factor
        )
    return totals


__all__ = [
    "reservoir_step_totals",
]
