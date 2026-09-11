from __future__ import annotations

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.surrogate.domain.physics_checks.pairwise import check_pair
from backend.contexts.surrogate.domain.physics_checks.single import check_prediction
from backend.contexts.surrogate.domain.physics_checks.types import (
    BhpLimits,
    DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
    DEFAULT_OIL_DENSITY_T_PER_M3,
    DEFAULT_RELATIVE_TOLERANCE,
    DEFAULT_WATERCUT_TOLERANCE,
    DEFAULT_ZERO_TOLERANCE,
    Invariant,
    PhysicsReport,
    _DIFFERENTIAL_INVARIANTS,
)
from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput


def check_physics(
    candidate: RawModelOutput,
    *,
    schedule: Schedule,
    reference: RawModelOutput | None = None,
    reference_schedule: Schedule | None = None,
    lam: Lambda | None = None,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    bhp_limits: BhpLimits | None = None,
    zero_tolerance: float = DEFAULT_ZERO_TOLERANCE,
    watercut_tolerance: float = DEFAULT_WATERCUT_TOLERANCE,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    single = check_prediction(
        candidate,
        schedule=schedule,
        oil_density_t_per_m3=oil_density_t_per_m3,
        bhp_limits=bhp_limits,
        zero_tolerance=zero_tolerance,
        watercut_tolerance=watercut_tolerance,
        max_examples=max_examples,
    )
    if reference is None or reference_schedule is None or lam is None:
        absent = "the reference" if reference is None or reference_schedule is None else "λ"
        return PhysicsReport(
            counts=single.counts,
            examples=single.examples,
            evaluated=single.evaluated,
            skipped={
                **single.skipped,
                **{
                    invariant.value: f"{absent} was not supplied: the invariant is undefined"
                    for invariant in _DIFFERENTIAL_INVARIANTS
                },
            },
            n_nodes=single.n_nodes,
            n_wells=single.n_wells,
        )

    pair = check_pair(
        reference,
        candidate,
        reference_schedule=reference_schedule,
        candidate_schedule=schedule,
        lam=lam,
        oil_density_t_per_m3=oil_density_t_per_m3,
        relative_tolerance=relative_tolerance,
        max_examples=max_examples,
    )
    counts = dict(single.counts)
    for name, count in pair.counts.items():
        counts[name] = counts.get(name, 0) + count
    skipped = {
        name: reason
        for name, reason in single.skipped.items()
        if Invariant(name) not in _DIFFERENTIAL_INVARIANTS
    }
    skipped.update(pair.skipped)
    return PhysicsReport(
        counts=counts,
        examples=single.examples + pair.examples,
        evaluated=single.evaluated + pair.evaluated,
        skipped=skipped,
        n_nodes=single.n_nodes,
        n_wells=single.n_wells,
    )


__all__ = [
    "check_physics",
]
