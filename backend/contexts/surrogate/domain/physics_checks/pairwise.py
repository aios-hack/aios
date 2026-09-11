from __future__ import annotations

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.schedule.domain.schedule import EventKind, Schedule
from backend.contexts.surrogate.domain.errors import PhysicsCheckError
from backend.contexts.surrogate.domain.physics_checks.types import (
    DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
    DEFAULT_OIL_DENSITY_T_PER_M3,
    DEFAULT_RELATIVE_TOLERANCE,
    Invariant,
    PhysicsReport,
    _DIFFERENTIAL_INVARIANTS,
    _FlagSink,
    _require_same_axis,
)
from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput


def injection_only_pair(
    reference_schedule: Schedule, candidate_schedule: Schedule
) -> tuple[bool, str]:
    def events(schedule: Schedule) -> dict[tuple[int, str, str], float | None]:
        return {
            (event.control_step, event.well, event.kind.value): getattr(event, "value", None)
            for event in schedule.control_events
        }

    left, right = events(reference_schedule), events(candidate_schedule)
    changed = {key for key in set(left) | set(right) if left.get(key) != right.get(key)}
    if not changed:
        return False, "the reference and the candidate carry identical control events"
    other = sorted({key[2] for key in changed} - {EventKind.SET_RATE.value})
    if other:
        return False, f"the candidate changes more than injection: {', '.join(other)}"
    return True, ""


def lambda_column_sums(lam: Lambda) -> dict[str, float]:
    sums: dict[str, float] = {}
    for column, injector in enumerate(lam.injectors):
        sums[injector] = sum(lam.matrix[row][column] for row in range(len(lam.producers)))
    return sums


def _dominant_neighbourhoods(lam: Lambda) -> dict[str, tuple[str, ...]]:
    neighbourhoods: dict[str, list[str]] = {injector: [] for injector in lam.injectors}
    for row, producer in enumerate(lam.producers):
        weights = lam.matrix[row]
        best = max(range(len(lam.injectors)), key=lambda column: weights[column])
        if weights[best] > 0.0:
            neighbourhoods[lam.injectors[best]].append(producer)
    return {injector: tuple(producers) for injector, producers in neighbourhoods.items()}


def check_pair(
    reference: RawModelOutput,
    candidate: RawModelOutput,
    *,
    reference_schedule: Schedule,
    candidate_schedule: Schedule,
    lam: Lambda,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    if oil_density_t_per_m3 <= 0.0:
        raise PhysicsCheckError("oil_density_t_per_m3 must be positive")
    if relative_tolerance < 0.0:
        raise PhysicsCheckError("relative_tolerance cannot be negative")
    if reference.wells != candidate.wells:
        raise PhysicsCheckError("the reference and the candidate are built on different well axes")
    if reference.canonical_schedule_hash == candidate.canonical_schedule_hash:
        raise PhysicsCheckError(
            "the reference and the candidate are one and the same schedule: differential invariants are undefined"
        )

    known = set(reference.wells)
    missing = (set(lam.producers) | set(lam.injectors)) - known
    if missing:
        raise PhysicsCheckError(
            f"λ references wells outside the forecast: {sorted(missing)[:5]}"
        )

    identifiable, reason = injection_only_pair(reference_schedule, candidate_schedule)
    if not identifiable:
        return PhysicsReport(
            counts={},
            examples=(),
            evaluated=(),
            skipped={invariant.value: reason for invariant in _DIFFERENTIAL_INVARIANTS},
            n_nodes=len(candidate.nodes),
            n_wells=len(candidate.wells),
        )

    delta_liquid = _horizon_delta(reference, candidate, "liquid_volume_delta")
    delta_oil_mass = _horizon_delta(reference, candidate, "oil_mass_delta")
    delta_injection = _horizon_delta(reference, candidate, "injection_volume_delta")
    sink = _FlagSink(max_examples)

    for injector, producers in _dominant_neighbourhoods(lam).items():
        injected = delta_injection.get(injector, 0.0)
        if not producers or injected <= _scaled_tolerance(injected, relative_tolerance):
            continue
        produced = sum(delta_liquid.get(producer, 0.0) for producer in producers)
        if produced < -_scaled_tolerance(injected, relative_tolerance):
            sink.add(
                Invariant.INJECTION_RESPONSE,
                well=injector,
                observed=produced,
                limit=0.0,
                detail=(
                    f"injection rose by {injected:.1f} m3, while the total liquid of "
                    f"{len(producers)} producers in its neighbourhood fell by {-produced:.1f} m3"
                ),
            )

    injected_total = sum(delta_injection.get(well, 0.0) for well in lam.injectors)
    water_total = sum(
        delta_liquid.get(producer, 0.0)
        - delta_oil_mass.get(producer, 0.0) / oil_density_t_per_m3
        for producer in lam.producers
    )
    tolerance = _scaled_tolerance(max(water_total, injected_total), relative_tolerance)
    if water_total > injected_total + tolerance:
        sink.add(
            Invariant.MATERIAL_BALANCE,
            well="<field>",
            observed=water_total,
            limit=injected_total,
            detail=(
                f"{water_total:.1f} m3 more water was produced while injection grew by "
                f"{injected_total:.1f} m3: the water came from nowhere"
            ),
        )

    return PhysicsReport(
        counts=sink.counts,
        examples=sink.examples,
        evaluated=_DIFFERENTIAL_INVARIANTS,
        skipped={},
        n_nodes=len(candidate.nodes),
        n_wells=len(candidate.wells),
    )


def _scaled_tolerance(magnitude: float, relative_tolerance: float) -> float:
    return abs(magnitude) * relative_tolerance


def _horizon_delta(
    reference: RawModelOutput, candidate: RawModelOutput, channel: str
) -> dict[str, float]:
    totals: dict[str, float] = {well: 0.0 for well in candidate.wells}
    for node in candidate.nodes:
        totals[node.well] += getattr(node, channel)
    for node in reference.nodes:
        totals[node.well] -= getattr(node, channel)
    return totals


__all__ = [
    "check_pair",
    "injection_only_pair",
    "lambda_column_sums",
]
