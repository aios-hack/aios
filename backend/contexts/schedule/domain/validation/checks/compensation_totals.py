from __future__ import annotations

from collections.abc import (
    Sequence,
)
from backend.contexts.connectivity.domain.connectivity import Groups
from backend.contexts.reservoir.domain.response import IntervalResponse


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
            f"conversion of compensation to reservoir conditions was "
            f"requested on step {control_step}, but the (B_o, B_w) pair for "
            f"it was not supplied: got {len(reservoir_factors)} pairs. "
            "Computing compensation from the factors of a neighbouring step "
            "would mean passing off a number nobody computed as a reservoir "
            "condition"
        )
    oil_factor, water_factor = reservoir_factors[control_step]
    if oil_factor <= 0.0 or water_factor <= 0.0:
        raise ValueError(
            f"the pair of formation volume factors on step {control_step} "
            f"is non-positive: B_o = {oil_factor}, B_w = {water_factor}; the "
            "volume under reservoir conditions is undefined for them"
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
            "conversion of compensation to reservoir conditions requires a "
            f"positive oil density, got {oil_density_t_per_m3} t/m3: the oil "
            "volume under surface conditions cannot be recovered from mass"
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
            "per-group compensation requires every well of the response to "
            f"belong to a group, left outside groups: "
            f"{', '.join(uncovered)}; computing C(k) over an incomplete "
            "split would mean declaring the check performed where part of "
            "the withdrawal and injection is not accounted for"
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
            "conversion of per-group compensation to reservoir conditions "
            "was requested without oil density: the oil volume in the "
            "withdrawal cannot be recovered"
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
