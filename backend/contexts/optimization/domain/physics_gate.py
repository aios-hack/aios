from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    _DIFFERENTIAL_INVARIANT_NAMES,
    MissingReferenceError,
    PhysicallyImpossibleScheduleError,
)

from backend.contexts.surrogate.domain.physics_checks import (
    Invariant,
    PhysicsCheckError,
    PhysicsReport,
    Severity,
    check_pair,
    check_prediction,
    severity_of,
)
from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput
from typing import (
    Mapping,
)
from backend.core.contracts import (
    Schedule,
)


def missing_invariants(report: PhysicsReport) -> tuple[str, ...]:
    evaluated = {invariant.value for invariant in report.evaluated}
    return tuple(
        invariant.value for invariant in Invariant if invariant.value not in evaluated
    )


def _incompleteness_description(report: PhysicsReport) -> str:
    parts: list[str] = []
    for name in missing_invariants(report):
        reason = report.skipped.get(name)
        parts.append(name if reason is None else f"{name} ({reason})")
    return (
        "physics_complete=false: проверка неполная, не посчитаны инварианты: "
        + "; ".join(parts)
    )


def _enforce_physics(
    report: PhysicsReport,
    enabled: bool,
    baseline: Mapping[str, int] | None = None,
) -> None:
    if not enabled or report.admissible:
        return
    if not report.complete:
        missing = missing_invariants(report)
        raise PhysicallyImpossibleScheduleError(
            {}, _incompleteness_description(report), missing
        )
    blocking = {
        name: count
        for name, count in sorted(report.counts.items())
        if severity_of(name) is Severity.BLOCKING
    }
    description = "physics_complete=true; " + ", ".join(
        f"{name}×{count}" for name, count in blocking.items()
    )
    example = next(
        (flag for flag in report.examples if flag.severity is Severity.BLOCKING), None
    )
    if example is not None:
        description += (
            f"; например скважина {example.well}, шаг {example.control_step}: "
            f"{example.detail}"
        )
    raise PhysicallyImpossibleScheduleError(blocking, description)


def full_physics_report(
    env: SearchEnvironment, schedule: Schedule, candidate: RawModelOutput
) -> PhysicsReport:
    if env.reference_schedule is None or env.reference_response is None:
        raise MissingReferenceError(
            "провенанс опоры: "
            + env.provenance.get("reference", "absent: опора не строилась")
        )
    single = check_prediction(
        candidate, schedule=schedule, oil_density_t_per_m3=env.oil_density_t_per_m3
    )
    if (
        candidate.canonical_schedule_hash
        == env.reference_response.canonical_schedule_hash
        and not getattr(env, "physics_gate", True)
    ):
        skipped = {
            name: reason
            for name, reason in single.skipped.items()
            if name not in _DIFFERENTIAL_INVARIANT_NAMES
        }
        skipped.update(
            {
                name: MissingReferenceError.SELF_REFERENCE
                for name in _DIFFERENTIAL_INVARIANT_NAMES
            }
        )
        return PhysicsReport(
            counts=dict(single.counts),
            examples=single.examples,
            evaluated=single.evaluated,
            skipped=skipped,
            n_nodes=single.n_nodes,
            n_wells=single.n_wells,
        )
    try:
        pair = check_pair(
            env.reference_response,
            candidate,
            reference_schedule=env.reference_schedule,
            candidate_schedule=schedule,
            lam=env.lambda_,
            oil_density_t_per_m3=env.oil_density_t_per_m3,
        )
    except PhysicsCheckError as error:
        raise MissingReferenceError(
            f"пара опора/кандидат непригодна для проверки: {error}"
        ) from error
    counts = dict(single.counts)
    for name, count in pair.counts.items():
        counts[name] = counts.get(name, 0) + count
    skipped = {
        name: reason
        for name, reason in single.skipped.items()
        if name not in _DIFFERENTIAL_INVARIANT_NAMES
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


def physics_counters(report: PhysicsReport) -> dict[str, int]:
    counters = {name: int(count) for name, count in sorted(report.counts.items())}
    counters["blocking_count"] = int(report.blocking_count)
    counters["warning_count"] = int(report.warning_count)
    counters["complete"] = int(report.complete)
    counters["admissible"] = int(report.admissible)
    return counters


__all__ = [
    "full_physics_report",
    "missing_invariants",
    "physics_counters",
]
