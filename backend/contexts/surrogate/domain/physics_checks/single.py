from __future__ import annotations

import math

from backend.contexts.schedule.domain.schedule import (
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
)
from backend.contexts.simulation.domain.well_timeline import build_well_timelines
from backend.contexts.surrogate.domain.errors import PhysicsCheckError
from backend.contexts.surrogate.domain.physics_checks.types import (
    BhpLimits,
    DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
    DEFAULT_OIL_DENSITY_T_PER_M3,
    DEFAULT_WATERCUT_TOLERANCE,
    DEFAULT_ZERO_TOLERANCE,
    Invariant,
    PhysicsReport,
    _DIFFERENTIAL_INVARIANTS,
    _FlagSink,
    _RATE_CHANNELS,
    _SINGLE_PREDICTION_INVARIANTS,
    _VOLUME_CHANNELS,
    _require_same_axis,
)
from backend.contexts.surrogate.domain.raw_model_output import (
    RawModelOutput,
    RawWellStepPrediction,
)
from backend.contexts.surrogate.domain.schedule_roles import build_role_timelines


def check_prediction(
    raw: RawModelOutput,
    *,
    schedule: Schedule,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    bhp_limits: BhpLimits | None = None,
    zero_tolerance: float = DEFAULT_ZERO_TOLERANCE,
    watercut_tolerance: float = DEFAULT_WATERCUT_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    if oil_density_t_per_m3 <= 0.0:
        raise PhysicsCheckError("oil_density_t_per_m3 must be positive")
    if zero_tolerance < 0.0:
        raise PhysicsCheckError("zero_tolerance cannot be negative")
    if watercut_tolerance < 0.0:
        raise PhysicsCheckError("watercut_tolerance cannot be negative")
    _require_same_axis(raw, schedule)

    limits = bhp_limits if bhp_limits is not None else BhpLimits.from_schedule(schedule)
    role_timelines = build_role_timelines(schedule)
    well_timelines = build_well_timelines(schedule)
    sink = _FlagSink(max_examples)

    evaluated = list(_SINGLE_PREDICTION_INVARIANTS)
    skipped: dict[str, str] = {
        invariant.value: "the invariant is defined only on a reference/candidate pair"
        for invariant in _DIFFERENTIAL_INVARIANTS
    }
    if not limits.usable:
        evaluated.remove(Invariant.BHP_LIMIT)
        skipped[Invariant.BHP_LIMIT.value] = (
            "the deck sets no BHP limits for any well: "
            "WCONPROD/WCONINJE carry no numeric limit value"
        )

    for node in raw.nodes:
        role = role_timelines[node.well].role(node.control_step)
        _check_non_negative(node, sink=sink, tolerance=zero_tolerance)
        _check_watercut(
            node,
            sink=sink,
            oil_density_t_per_m3=oil_density_t_per_m3,
            zero_tolerance=zero_tolerance,
            watercut_tolerance=watercut_tolerance,
        )
        _check_cumulative(node, sink=sink, tolerance=zero_tolerance)
        _check_shut_well(
            node,
            sink=sink,
            timeline=well_timelines[node.well],
            tolerance=zero_tolerance,
        )
        if Invariant.BHP_LIMIT in evaluated:
            _check_bhp(node, sink=sink, role=role, limits=limits)

    return PhysicsReport(
        counts=sink.counts,
        examples=sink.examples,
        evaluated=tuple(evaluated),
        skipped=skipped,
        n_nodes=len(raw.nodes),
        n_wells=len(raw.wells),
    )


def _check_non_negative(
    node: RawWellStepPrediction, *, sink: _FlagSink, tolerance: float
) -> None:
    for channel in _RATE_CHANNELS + _VOLUME_CHANNELS + ("bhp",):
        value = getattr(node, channel)
        if not math.isfinite(value):
            sink.add(
                Invariant.NON_NEGATIVE,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel} is not finite",
            )
        elif value < -tolerance:
            sink.add(
                Invariant.NON_NEGATIVE,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel} is negative",
            )


def _check_watercut(
    node: RawWellStepPrediction,
    *,
    sink: _FlagSink,
    oil_density_t_per_m3: float,
    zero_tolerance: float,
    watercut_tolerance: float,
) -> None:
    liquid = node.liquid_volume_delta
    oil_volume = node.oil_mass_delta / oil_density_t_per_m3
    if liquid <= zero_tolerance:
        if oil_volume > zero_tolerance:
            sink.add(
                Invariant.WATERCUT_RANGE,
                well=node.well,
                control_step=node.control_step,
                observed=oil_volume,
                limit=0.0,
                detail="oil without liquid: watercut is undefined and below zero",
            )
        return
    watercut = 1.0 - oil_volume / liquid
    if watercut < -watercut_tolerance:
        sink.add(
            Invariant.WATERCUT_RANGE,
            well=node.well,
            control_step=node.control_step,
            observed=watercut,
            limit=0.0,
            detail=(
                f"{oil_volume:.3f} m3 of oil against {liquid:.3f} m3 of liquid: "
                f"watercut {watercut:.6f} is below zero"
            ),
        )
    elif watercut > 1.0 + watercut_tolerance:
        sink.add(
            Invariant.WATERCUT_RANGE,
            well=node.well,
            control_step=node.control_step,
            observed=watercut,
            limit=1.0,
            detail=f"watercut {watercut:.6f} is above one: oil production is negative",
        )


def _check_cumulative(
    node: RawWellStepPrediction, *, sink: _FlagSink, tolerance: float
) -> None:
    for channel in _VOLUME_CHANNELS:
        value = getattr(node, channel)
        if math.isfinite(value) and value < -tolerance:
            sink.add(
                Invariant.CUMULATIVE_MONOTONIC,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel}: the cumulative value decreases over the interval",
            )


def _check_shut_well(
    node: RawWellStepPrediction, *, sink: _FlagSink, timeline: object, tolerance: float
) -> None:
    commissioned = timeline.is_commissioned(node.control_step)  # type: ignore[attr-defined]
    status = timeline.operating_status(node.control_step)  # type: ignore[attr-defined]
    if commissioned and status is OperatingStatus.OPEN:
        return
    reason = "not commissioned" if not commissioned else "shut"
    for channel in _RATE_CHANNELS + _VOLUME_CHANNELS:
        value = getattr(node, channel)
        if math.isfinite(value) and abs(value) > tolerance:
            sink.add(
                Invariant.SHUT_WELL_FLOW,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"the well is {reason}, yet {channel} is not zero",
            )


def _check_bhp(
    node: RawWellStepPrediction, *, sink: _FlagSink, role: Role, limits: BhpLimits
) -> None:
    if role is Role.PROD:
        floor = limits.floor_for(node.well)
        if floor is not None and node.bhp < floor:
            sink.add(
                Invariant.BHP_LIMIT,
                well=node.well,
                control_step=node.control_step,
                observed=node.bhp,
                limit=floor,
                detail=f"bottomhole {node.bhp:.2f} bar is below the producer floor {floor:.2f} bar",
            )
    elif role is Role.INJ:
        ceiling = limits.ceiling_for(node.well)
        if ceiling is not None and node.bhp > ceiling:
            sink.add(
                Invariant.BHP_LIMIT,
                well=node.well,
                control_step=node.control_step,
                observed=node.bhp,
                limit=ceiling,
                detail=(
                    f"bottomhole {node.bhp:.2f} bar is above the injector ceiling "
                    f"{ceiling:.2f} bar"
                ),
            )


__all__ = [
    "check_prediction",
]
