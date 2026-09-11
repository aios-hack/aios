from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from backend.contexts.optimization.domain.errors import ComparisonError
from backend.contexts.runs.infrastructure.provenance import git_commit
from backend.contexts.schedule.domain.case_limits import (
    CaseLimitsError,
    CaseLimitsOutcome,
    ProductionForecastFn,
    apply_case_limits_report,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.simulation.application.submission import SubmissionResult
from backend.shared.hashing import hash_schedule

from backend.contexts.optimization.application.verification_guard import GuardReport


COMPARISON_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class ComparisonSide:
    name: str
    schedule: Schedule
    result: SubmissionResult
    guard: GuardReport
    wallclock_seconds: float
    opm_runs: int
    projection: CaseLimitsOutcome | None = None

    @property
    def npv(self) -> float | None:
        if self.result.final_npv is None:
            return None
        return float(self.result.final_npv.npv_methodology)

    @property
    def blocking_violations(self) -> int | None:
        if self.result.dynamic_report is None:
            return None
        return len(self.result.dynamic_report.blocking_violations)

    @property
    def dynamic_violations(self) -> int | None:
        if self.result.dynamic_report is None:
            return None
        return len(self.result.dynamic_report.violations)

    @property
    def static_violations(self) -> int:
        return len(self.result.static_report.violations)

    def violations_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        if self.result.dynamic_report is None:
            return counts
        for violation in self.result.dynamic_report.violations:
            key = str(getattr(violation.kind, "name", violation.kind))
            counts[key] = counts.get(key, 0) + 1
        return counts


def _side_npv_or_refuse(side: ComparisonSide) -> float:
    npv = side.npv
    if npv is None:
        raise ComparisonError(
            f"side \"{side.name}\" produced no NPV: the pipeline stopped at status "
            f"{side.result.opm_run.status}, the economics were not computed. The "
            "comparison is abandoned — substituting zero for an uncomputed "
            "number is forbidden"
        )
    return npv


def project_baseline(
    baseline: Schedule,
    constraints: Constraints,
    control_dates: Sequence[date],
    forecast: ProductionForecastFn | None,
) -> CaseLimitsOutcome:
    if forecast is None:
        raise ComparisonError(
            "projecting the baseline schedule onto the case is impossible: the annual "
            "production forecast (ProductionForecastFn) was not supplied. Cutting "
            "by the sum of setpoints yields an understated baseline and makes the "
            "comparison dishonest — supply the forecast or drop the comparison"
        )
    try:
        return apply_case_limits_report(baseline, constraints, control_dates, forecast)
    except CaseLimitsError as error:
        raise ComparisonError(
            f"the baseline schedule was not projected onto the case: {error}"
        ) from error

@dataclass(frozen=True, slots=True)
class ConditionCheck:
    name: str
    baseline: str
    candidate: str

    @property
    def holds(self) -> bool:
        return self.baseline == self.candidate

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "holds": self.holds,
            "baseline": self.baseline,
            "candidate": self.candidate,
        }


def equal_conditions(
    baseline: ComparisonSide,
    candidate: ComparisonSide,
    *,
    case_hash: str,
    baseline_deck_hash: str,
    candidate_deck_hash: str,
    image: str,
) -> tuple[ConditionCheck, ...]:
    return (
        ConditionCheck(
            name="constraints_hash",
            baseline=baseline.guard.constraints.actual,
            candidate=candidate.guard.constraints.actual,
        ),
        ConditionCheck(name="case_hash", baseline=case_hash, candidate=case_hash),
        ConditionCheck(
            name="deck_hash",
            baseline=baseline_deck_hash,
            candidate=candidate_deck_hash,
        ),
        ConditionCheck(name="opm_image", baseline=image, candidate=image),
    )


def refuse_unequal_conditions(checks: Sequence[ConditionCheck]) -> None:
    broken = [check for check in checks if not check.holds]
    if not broken:
        return
    details = "; ".join(
        f"{check.name}: baseline {check.baseline}, candidate {check.candidate}"
        for check in broken
    )
    raise ComparisonError(
        "comparison abandoned: the runs were not made under the same conditions — " + details
    )


def _count_text(value: int | None) -> str:
    return "—" if value is None else str(value)


def _delta_text(baseline: int | None, candidate: int | None) -> str:
    if baseline is None or candidate is None:
        return "—"
    return f"{candidate - baseline:+d}"


def _side_document(side: ComparisonSide, npv: float) -> dict[str, object]:
    projection = side.projection
    return {
        "name": side.name,
        "canonical_schedule_hash": hash_schedule(side.schedule),
        "npv_rub": npv,
        "npv_bln_rub": npv / 1e9,
        "run_id": side.result.opm_run.run_id,
        "run_status": str(side.result.opm_run.status),
        "sound": side.result.sound,
        "violations": {
            "static": side.static_violations,
            "dynamic": side.dynamic_violations,
            "blocking": side.blocking_violations,
            "by_kind": side.violations_by_kind(),
        },
        "failed_identities": [check.name for check in side.result.failed_identities],
        "wallclock_seconds": side.wallclock_seconds,
        "opm_runs": side.opm_runs,
        "case_projection": None
        if projection is None
        else {
            "applied": True,
            "forecast_used": projection.forecast_used,
            "setpoint_sum_fallback": projection.setpoint_sum_fallback,
            "rounds": projection.rounds,
            "trimmed_years": {
                kind.name: list(years) for kind, years in projection.trimmed_years.items()
            },
        },
    }


def _comparison_table(
    baseline: ComparisonSide,
    candidate: ComparisonSide,
    baseline_npv: float,
    candidate_npv: float,
) -> list[dict[str, str]]:
    delta = candidate_npv - baseline_npv
    return [
        {
            "metric": "NPV, bln RUB",
            "baseline": f"{baseline_npv / 1e9:.3f}",
            "candidate": f"{candidate_npv / 1e9:.3f}",
            "delta": f"{delta / 1e9:+.3f}",
        },
        {
            "metric": "Gain vs baseline, %",
            "baseline": "—",
            "candidate": f"{100.0 * delta / baseline_npv:+.2f}",
            "delta": "—",
        },
        {
            "metric": "Blocking violations",
            "baseline": _count_text(baseline.blocking_violations),
            "candidate": _count_text(candidate.blocking_violations),
            "delta": _delta_text(
                baseline.blocking_violations, candidate.blocking_violations
            ),
        },
        {
            "metric": "Dynamic violations",
            "baseline": _count_text(baseline.dynamic_violations),
            "candidate": _count_text(candidate.dynamic_violations),
            "delta": _delta_text(
                baseline.dynamic_violations, candidate.dynamic_violations
            ),
        },
        {
            "metric": "Time, s",
            "baseline": f"{baseline.wallclock_seconds:.1f}",
            "candidate": f"{candidate.wallclock_seconds:.1f}",
            "delta": f"{candidate.wallclock_seconds - baseline.wallclock_seconds:+.1f}",
        },
        {
            "metric": "OPM runs",
            "baseline": str(baseline.opm_runs),
            "candidate": str(candidate.opm_runs),
            "delta": str(baseline.opm_runs + candidate.opm_runs),
        },
    ]


def build_comparison_document(
    baseline: ComparisonSide,
    candidate: ComparisonSide,
    *,
    case_path: Path,
    case_hash: str,
    baseline_deck_hash: str,
    candidate_deck_hash: str,
    image: str,
    run_id: str,
) -> dict[str, object]:
    checks = equal_conditions(
        baseline,
        candidate,
        case_hash=case_hash,
        baseline_deck_hash=baseline_deck_hash,
        candidate_deck_hash=candidate_deck_hash,
        image=image,
    )
    refuse_unequal_conditions(checks)
    baseline_npv = _side_npv_or_refuse(baseline)
    candidate_npv = _side_npv_or_refuse(candidate)
    if baseline_npv == 0.0:
        raise ComparisonError(
            "the baseline NPV is zero: the relative gain is undefined, there is "
            "nothing to print percentages from"
        )
    delta = candidate_npv - baseline_npv
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "run_id": run_id,
        "conditions": {
            "equal": True,
            "case_path": str(case_path),
            "case_hash": case_hash,
            "constraints_hash": candidate.guard.constraints.actual,
            "deck_hash": candidate_deck_hash,
            "opm_image": image,
            "git_commit": git_commit(),
            "checks": [check.as_dict() for check in checks],
        },
        "baseline": _side_document(baseline, baseline_npv),
        "candidate": _side_document(candidate, candidate_npv),
        "delta": {
            "npv_rub": delta,
            "npv_bln_rub": delta / 1e9,
            "npv_percent": 100.0 * delta / baseline_npv,
            "blocking_violations": None
            if baseline.blocking_violations is None
            or candidate.blocking_violations is None
            else candidate.blocking_violations - baseline.blocking_violations,
            "wallclock_seconds": candidate.wallclock_seconds - baseline.wallclock_seconds,
        },
        "totals": {
            "opm_runs": baseline.opm_runs + candidate.opm_runs,
            "wallclock_seconds": baseline.wallclock_seconds + candidate.wallclock_seconds,
        },
        "table": _comparison_table(baseline, candidate, baseline_npv, candidate_npv),
    }


COMPARISON_COLUMNS: tuple[str, ...] = ("metric", "baseline", "candidate", "delta")
COMPARISON_HEADER: tuple[str, ...] = ("Metric", "Baseline", "Candidate", "Δ")


def print_comparison(document: dict[str, object]) -> None:
    table = document["table"]
    if not isinstance(table, list):
        raise ComparisonError("the comparison document has no table to print")
    widths = [
        max([len(title)] + [len(str(row[key])) for row in table])
        for key, title in zip(COMPARISON_COLUMNS, COMPARISON_HEADER)
    ]
    line = "  ".join(
        title.ljust(width) for title, width in zip(COMPARISON_HEADER, widths)
    )
    print(line, flush=True)
    print("-" * len(line), flush=True)
    for row in table:
        print(
            "  ".join(
                str(row[key]).ljust(width)
                for key, width in zip(COMPARISON_COLUMNS, widths)
            ),
            flush=True,
        )

