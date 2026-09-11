
from __future__ import annotations

from backend.contexts.simulation.domain.errors import (
    SubmissionTractError,
)

import shutil
from dataclasses import dataclass
from pathlib import Path

from backend.contexts.constraints.domain.schema import economics_config_hash
from backend.contexts.connectivity.domain.connectivity import Groups
from backend.contexts.constraints.domain.config import Config
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.runs.domain.run_result import (
    FinalNpvArtifact,
    OpmRunArtifact,
    ResponseArtifact,
    RunStatus,
)
from backend.contexts.schedule.domain.schedule import Schedule
from backend.shared.hashing import hash_schedule
from backend.contexts.economics.domain.methodology_hash import methodology_version_hash
from backend.contexts.economics.application.base_case import analyze_base_case
from backend.contexts.schedule.domain.validate_dynamic import DynamicReport, validate_dynamic
from backend.contexts.schedule.domain.validate import ValidationReport, validate_static
from backend.contexts.schedule.domain.lossless import parse_schedule

from backend.contexts.simulation.infrastructure.cache import CachingOpmRunner, RunCache
from backend.contexts.reservoir.infrastructure.opm_deck import OpmDeckEmitter
from backend.contexts.simulation.infrastructure.response_loader import (
    ResponseLoader,
    load_density_by_pvtnum,
)
from backend.contexts.simulation.infrastructure.runner import OpmRunner

_SCHEDULE_INCLUDE = "Model_Z_sch.inc"


@dataclass(frozen=True, slots=True)
class IdentityCheck:
    name: str
    holds: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    static_report: ValidationReport
    opm_run: OpmRunArtifact
    response: ResponseArtifact | None
    dynamic_report: DynamicReport | None
    final_npv: FinalNpvArtifact | None
    identities: tuple[IdentityCheck, ...]

    @property
    def failed_identities(self) -> tuple[IdentityCheck, ...]:
        return tuple(check for check in self.identities if not check.holds)

    @property
    def sound(self) -> bool:
        return (
            self.static_report.ok
            and self.dynamic_report is not None
            and self.dynamic_report.blocking_ok
            and self.opm_run.status is RunStatus.OK
            and self.final_npv is not None
            and all(check.holds for check in self.identities)
        )

    @property
    def npv_methodology(self) -> float:
        if not self.sound or self.final_npv is None:
            raise SubmissionTractError(
                "the submission chain did not pass, there is no number to declare: "
                + _failure_summary(self)
            )
        return self.final_npv.npv_methodology


def _failure_summary(result: SubmissionResult) -> str:
    reasons: list[str] = []
    if not result.static_report.ok:
        reasons.append(
            f"validate_static: {len(result.static_report.violations)} violations, "
            f"first one — {result.static_report.violations[0]}"
        )
    if result.dynamic_report is None:
        reasons.append("validate_dynamic was not run: the response was not read")
    elif not result.dynamic_report.ok:
        reasons.append(
            f"validate_dynamic: {len(result.dynamic_report.report.violations)} "
            f"violations, first one — {result.dynamic_report.report.violations[0]}"
        )
    reasons.extend(f"{check.name}: {check.detail}" for check in result.failed_identities)
    return "; ".join(reasons)


def _run(
    schedule: Schedule,
    model_dir: Path,
    work_root: Path,
    *,
    use_cache: bool,
) -> tuple[OpmRunArtifact, ResponseArtifact | None]:
    emitter = OpmDeckEmitter(model_dir)
    deck_dir = work_root / "deck"
    if deck_dir.exists():
        shutil.rmtree(deck_dir)
    deck = emitter.emit(schedule, deck_dir)

    base_runner = OpmRunner(work_root / "runs")
    runner = (
        CachingOpmRunner(base_runner, RunCache(work_root / "cache")) if use_cache else base_runner
    )

    result = runner.run(deck, schedule)
    opm_run = OpmRunArtifact(
        run_id=result.run_id,
        status=result.status,
        deck_hash=result.deck_hash,
        canonical_schedule_hash=result.canonical_schedule_hash,
        summary_hash=result.summary_hash,
        artifacts=result.artifacts,
        wallclock_seconds=result.wallclock_seconds,
        message=result.message,
        content_hash_opm=deck.content_hash_opm,
    )

    if opm_run.status is not RunStatus.OK:
        return opm_run, None

    density_by_pvtnum = load_density_by_pvtnum(model_dir)
    response = ResponseLoader().load(opm_run, deck.summary_plan, schedule, density_by_pvtnum)
    return opm_run, response


def _identities(
    *,
    schedule: Schedule,
    opm_run: OpmRunArtifact,
    response: ResponseArtifact | None,
    final_npv: FinalNpvArtifact | None,
    expected_economics_hash: str,
    expected_methodology_hash: str,
) -> tuple[IdentityCheck, ...]:
    recomputed = hash_schedule(schedule)
    checks = [
        IdentityCheck(
            name="run_schedule_hash",
            holds=opm_run.canonical_schedule_hash == recomputed,
            detail=(
                f"the run schedule hash {opm_run.canonical_schedule_hash!r} against "
                f"the one recomputed at submission time {recomputed!r} — the schedule "
                f"was substituted after the last run"
            ),
        ),
        IdentityCheck(
            name="run_status_ok",
            holds=opm_run.status is RunStatus.OK,
            detail=(
                f"status={opm_run.status}: a run that did not converge cannot be "
                f"the source of the declared number ({opm_run.message})"
            ),
        ),
    ]

    if response is None:
        checks.append(
            IdentityCheck(
                name="response_source_run_id",
                holds=False,
                detail="the response was not read: there is nothing to tie the run to a response with",
            )
        )
    else:
        checks.append(
            IdentityCheck(
                name="response_source_run_id",
                holds=response.source_run_id == opm_run.run_id,
                detail=(
                    f"ResponseArtifact.source_run_id {response.source_run_id!r} != "
                    f"OpmRunArtifact.run_id {opm_run.run_id!r} — ResponseLoader "
                    f"read the artifacts of the wrong launch"
                ),
            )
        )

    if final_npv is None:
        checks.extend(
            IdentityCheck(
                name=name,
                holds=False,
                detail="NPV was not computed: there is nothing to cross-check",
            )
            for name in ("npv_source_provenance", "economics_config_hash", "methodology_version_hash")
        )
        return tuple(checks)

    checks.append(
        IdentityCheck(
            name="npv_source_provenance",
            holds=(
                final_npv.source_run_id == opm_run.run_id
                and response is not None
                and final_npv.source_response_hash == response.response_hash
            ),
            detail=(
                f"FinalNpvArtifact.source_run_id {final_npv.source_run_id!r} / "
                f"source_response_hash {final_npv.source_response_hash!r} did not match "
                f"the run and the response — Economics was given the response of a different "
                f"run, or one substituted after it was read"
            ),
        )
    )
    checks.append(
        IdentityCheck(
            name="economics_config_hash",
            holds=final_npv.economics_config_hash == expected_economics_hash,
            detail=(
                f"economics_config_hash {final_npv.economics_config_hash!r} != "
                f"the recomputed {expected_economics_hash!r} — the number was computed with "
                f"different normatives"
            ),
        )
    )
    checks.append(
        IdentityCheck(
            name="methodology_version_hash",
            holds=final_npv.methodology_version_hash == expected_methodology_hash,
            detail=(
                f"methodology_version_hash {final_npv.methodology_version_hash!r} != "
                f"the recomputed {expected_methodology_hash!r} — the number was computed "
                f"by a different calculator version"
            ),
        )
    )
    return tuple(checks)


def submit_schedule(
    schedule: Schedule,
    model_dir: Path,
    work_root: Path,
    config: Config,
    *,
    constraints: Constraints | None = None,
    use_cache: bool = True,
    strict: bool = True,
    oil_density_t_per_m3: float | None = None,
    groups: Groups | None = None,
) -> SubmissionResult:
    static_report = validate_static(schedule, constraints)
    if not static_report.ok:
        raise SubmissionTractError(
            f"validate_static(Schedule*) == [] does not hold: "
            f"{len(static_report.violations)} violations, first one — "
            f"{static_report.violations[0]}"
        )

    opm_run, response = _run(schedule, model_dir, work_root, use_cache=use_cache)

    parsed = parse_schedule((Path(model_dir) / _SCHEDULE_INCLUDE).read_bytes())
    dynamic_report = None
    final_npv = None
    expected_economics_hash = economics_config_hash(config)
    expected_methodology_hash = methodology_version_hash()

    if response is not None:
        dynamic_report = validate_dynamic(
            schedule,
            response.state_at_date,
            response.interval_response,
            constraints,
            oil_density_t_per_m3=oil_density_t_per_m3,
            report_undershoot=False,
            groups=groups,
        )
        analysis = analyze_base_case(
            response,
            parsed.dates,
            parsed.t0_deck_date_index,
            config.normatives,
            config.policies,
        )
        final_npv = FinalNpvArtifact(
            npv_table=analysis.table,
            npv_methodology=analysis.table.npv_methodology,
            source_run_id=opm_run.run_id,
            source_response_hash=response.response_hash,
            economics_config_hash=expected_economics_hash,
            methodology_version_hash=expected_methodology_hash,
        )

    result = SubmissionResult(
        static_report=static_report,
        opm_run=opm_run,
        response=response,
        dynamic_report=dynamic_report,
        final_npv=final_npv,
        identities=_identities(
            schedule=schedule,
            opm_run=opm_run,
            response=response,
            final_npv=final_npv,
            expected_economics_hash=expected_economics_hash,
            expected_methodology_hash=expected_methodology_hash,
        ),
    )

    if strict and not result.sound:
        raise SubmissionTractError(
            f"link A §10.5 did not pass: {_failure_summary(result)}"
        )
    return result
