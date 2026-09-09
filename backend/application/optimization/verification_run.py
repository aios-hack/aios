from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Sequence

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.infrastructure.opm import SubmissionResult, submit_schedule
from backend.infrastructure.opm.opm_deck import OpmDeckEmitter
from backend.infrastructure.opm.runner import deck_hashes, summary_spec_hash
from backend.domain.configuration.schema import default_config
from backend.core.contracts import ArtifactHashes, Constraints, Schedule, Theta
from backend.core.contracts.hashing import canonical_bytes, hash_schedule
from backend.domain.schedule.canonical import canonical_part_hash
from backend.domain.schedule.json_io import load_schedule_json
from backend.domain.economics import (
    load_normatives,
    load_response_artifact,
    save_response_artifact,
)
from backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from backend.application.optimization.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.application.optimization.search_run import (
    CONSTRAINTS,
    FINAL_CAP,
    SEED,
    _peak_step_production,
    _repair_predicted_water_balance,
)
from backend.domain.policy.fixed_point import resolve
from backend.domain.policy.theta import default_theta
from backend.infrastructure.resources import chdd_python_dir, model_z_dir
from backend.domain.configuration.constraints_io import (
    constraints_from_json,
    constraints_hash,
)
from backend.domain.schedule.case_limits import (
    CaseLimitsError,
    CaseLimitsOutcome,
    ProductionForecastFn,
    apply_case_limits_report,
)
from backend.core.provenance import git_commit, opm_image

LAMBDA = Path("data/lambda-window-2007/lambda.json")
RESPONSE = Path("data/base_case/response.json")
WORK_ROOT = Path("data/g7-submission")
EXPECTED_HASH: str | None = None
BASE_NPV = 11_873_122_324.91
OIL_DENSITY_T_PER_M3 = 0.9131


class VerificationGuardError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GuardCheck:
    name: str
    expected: str | None
    actual: str
    source: str

    @property
    def checked(self) -> bool:
        return self.expected is not None

    @property
    def holds(self) -> bool:
        return self.expected is not None and self.expected == self.actual

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "checked": self.checked,
            "holds": self.holds,
            "expected": self.expected,
            "actual": self.actual,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class GuardReport:
    schedule: GuardCheck
    constraints: GuardCheck

    @property
    def checks(self) -> tuple[GuardCheck, ...]:
        return (self.schedule, self.constraints)

    @property
    def unchecked(self) -> tuple[GuardCheck, ...]:
        return tuple(check for check in self.checks if not check.checked)

    @property
    def fully_checked(self) -> bool:
        return not self.unchecked

    def as_dict(self) -> dict[str, object]:
        return {
            "fully_checked": self.fully_checked,
            "unchecked": [check.name for check in self.unchecked],
            "checks": [check.as_dict() for check in self.checks],
        }

    def raise_if_broken(self) -> None:
        broken = [
            check for check in self.checks if check.checked and not check.holds
        ]
        if not broken:
            return
        details = "; ".join(
            f"{check.name}: в прогоне {check.expected}, предъявлено "
            f"{check.actual} (источник эталона: {check.source})"
            for check in broken
        )
        raise VerificationGuardError(
            "верификация прекращена до запуска Flow: предъявленное к проверке "
            f"расходится с зафиксированным в прогоне — {details}"
        )


def _load_constraints() -> Constraints:
    return constraints_from_json(
        json.loads(CONSTRAINTS.read_text(encoding="utf-8"))
    )


def _read_manifest(run_dir: Path) -> dict[str, object]:
    path = run_dir / "manifest.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VerificationGuardError(
            f"манифест прогона не объект JSON: {path}"
        )
    return document


def _manifest_hash(document: dict[str, object], field: str, run_dir: Path) -> str | None:
    value = document.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise VerificationGuardError(
            f"манифест прогона {run_dir} содержит {field}={value!r}; "
            "эталонный хеш должен быть непустой строкой"
        )
    return value


def _run_constraints_hash(run_dir: Path) -> str | None:
    path = run_dir / "inputs" / "constraints.json"
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VerificationGuardError(
            f"сохранённый кейс прогона не объект JSON: {path}"
        )
    return constraints_hash(constraints_from_json(document))


def resolve_guard_report(
    schedule: Schedule,
    constraints: Constraints,
    *,
    run_dir: Path | None = None,
    expected_schedule_hash: str | None = None,
    expected_constraints_hash: str | None = None,
) -> GuardReport:
    schedule_source = "аргумент expected_schedule_hash"
    constraints_source = "аргумент expected_constraints_hash"
    if expected_schedule_hash is None and EXPECTED_HASH is not None:
        expected_schedule_hash = EXPECTED_HASH
        schedule_source = "константа EXPECTED_HASH"
    if run_dir is not None:
        manifest = _read_manifest(run_dir)
        if expected_schedule_hash is None:
            expected_schedule_hash = _manifest_hash(
                manifest, "schedule_hash", run_dir
            )
            schedule_source = f"{run_dir / 'manifest.json'}:schedule_hash"
        if expected_constraints_hash is None:
            expected_constraints_hash = _manifest_hash(
                manifest, "constraints_hash", run_dir
            )
            constraints_source = f"{run_dir / 'manifest.json'}:constraints_hash"
        if expected_constraints_hash is None:
            expected_constraints_hash = _run_constraints_hash(run_dir)
            constraints_source = str(run_dir / "inputs" / "constraints.json")
    if expected_schedule_hash is None:
        schedule_source = "эталон не найден"
    if expected_constraints_hash is None:
        constraints_source = "эталон не найден"
    return GuardReport(
        schedule=GuardCheck(
            name="canonical_schedule_hash",
            expected=expected_schedule_hash,
            actual=hash_schedule(schedule),
            source=schedule_source,
        ),
        constraints=GuardCheck(
            name="constraints_hash",
            expected=expected_constraints_hash,
            actual=constraints_hash(constraints),
            source=constraints_source,
        ),
    )


def _guard_run_dir(work_root: Path, run_dir: Path | None) -> Path | None:
    if run_dir is not None:
        return run_dir
    candidate = work_root.parent
    if (candidate / "manifest.json").is_file() or (
        candidate / "inputs" / "constraints.json"
    ).is_file():
        return candidate
    return None


@dataclass(frozen=True, slots=True)
class GuardedVerification:
    result: SubmissionResult
    guard: GuardReport


def verify_schedule_with_guard(
    schedule: Schedule,
    work_root: Path,
    *,
    run_dir: Path | None = None,
    expected_schedule_hash: str | None = None,
    expected_constraints_hash: str | None = None,
    constraints: Constraints | None = None,
) -> GuardedVerification:
    used_constraints = constraints if constraints is not None else _load_constraints()
    guard = resolve_guard_report(
        schedule,
        used_constraints,
        run_dir=_guard_run_dir(work_root, run_dir),
        expected_schedule_hash=expected_schedule_hash,
        expected_constraints_hash=expected_constraints_hash,
    )
    work_root.mkdir(parents=True, exist_ok=True)
    (work_root / "verification-guard.json").write_text(
        json.dumps(guard.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    guard.raise_if_broken()
    for check in guard.unchecked:
        print(
            f"ВНИМАНИЕ: {check.name} не сверяется — эталон отсутствует, "
            f"фактическое значение {check.actual}",
            flush=True,
        )
    model_dir = model_z_dir()
    normatives_path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    normatives = load_normatives(normatives_path)
    emitter = OpmDeckEmitter(model_dir)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        hashes = deck_hashes(deck, schedule)
        summary_hash = summary_spec_hash(deck.summary_plan.spec)
    config = default_config(
        normatives,
        ArtifactHashes(
            deck_hash=hashes.deck_hash,
            history_prefix_hash=canonical_part_hash(schedule.initial_state),
            summary_spec_hash=summary_hash,
            groups_hash="0" * 64,
            dataset_version_hash="0" * 64,
            surrogate_checkpoint_hash="0" * 64,
        ),
        global_seed=SEED,
    )
    result = submit_schedule(
        schedule,
        model_dir,
        work_root,
        config,
        constraints=used_constraints,
        strict=False,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )
    return GuardedVerification(result=result, guard=guard)


def verify_schedule(
    schedule: Schedule,
    work_root: Path,
    *,
    run_dir: Path | None = None,
    expected_schedule_hash: str | None = None,
    expected_constraints_hash: str | None = None,
    constraints: Constraints | None = None,
) -> SubmissionResult:
    return verify_schedule_with_guard(
        schedule,
        work_root,
        run_dir=run_dir,
        expected_schedule_hash=expected_schedule_hash,
        expected_constraints_hash=expected_constraints_hash,
        constraints=constraints,
    ).result


def persist_observation(
    schedule: Schedule,
    result: SubmissionResult,
    *,
    predicted_npv: float | None,
    observation_root: Path = Path("data/opm-observations"),
    metadata: dict[str, object] | None = None,
    guard: GuardReport | None = None,
) -> Path:
    schedule_hash = hash_schedule(schedule)
    observation_dir = observation_root / schedule_hash
    observation_dir.mkdir(parents=True, exist_ok=True)
    (observation_dir / "schedule.json").write_bytes(canonical_bytes(schedule))
    if result.response is not None:
        save_response_artifact(result.response, observation_dir / "response.json")
    if result.dynamic_report is not None:
        (observation_dir / "dynamic-report.json").write_bytes(
            canonical_bytes(result.dynamic_report)
        )
    final_summary = None
    if result.final_npv is not None:
        final_summary = {
            "npv_methodology": result.final_npv.npv_methodology,
            "source_run_id": result.final_npv.source_run_id,
            "source_response_hash": result.final_npv.source_response_hash,
            "economics_config_hash": result.final_npv.economics_config_hash,
            "methodology_version_hash": result.final_npv.methodology_version_hash,
        }
        (observation_dir / "final-npv-summary.json").write_text(
            json.dumps(final_summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    (observation_dir / "observation.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": schedule_hash,
                "run_id": result.opm_run.run_id,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "predicted_npv": predicted_npv,
                "opm_npv": final_summary["npv_methodology"] if final_summary else None,
                "dynamic_violations": (
                    len(result.dynamic_report.violations)
                    if result.dynamic_report is not None
                    else None
                ),
                "verification_guard": guard.as_dict() if guard is not None else None,
                "metadata": metadata or {},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return observation_dir


COMPARISON_SCHEMA_VERSION = "1.0"


class ComparisonError(RuntimeError):
    pass


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
            f"сторона «{side.name}» не дала ЧДД: тракт остановился на статусе "
            f"{side.result.opm_run.status}, экономика не посчитана. Сравнение "
            "прекращено — подставлять ноль вместо непосчитанного числа запрещено"
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
            "проекция базового расписания на кейс невозможна: оценщик годового "
            "отбора (ProductionForecastFn) не передан. Резка по сумме уставок даёт "
            "заниженную базу, и сравнение станет недобросовестным — подключите "
            "оценщик или откажитесь от сравнения"
        )
    try:
        return apply_case_limits_report(baseline, constraints, control_dates, forecast)
    except CaseLimitsError as error:
        raise ComparisonError(
            f"базовое расписание не спроецировано на кейс: {error}"
        ) from error


def _deck_template_hash(schedule: Schedule, model_dir: Path) -> str:
    emitter = OpmDeckEmitter(model_dir)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        return deck_hashes(deck, schedule).deck_hash


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
        f"{check.name}: база {check.baseline}, кандидат {check.candidate}"
        for check in broken
    )
    raise ComparisonError(
        "сравнение прекращено: прогоны шли не в одних условиях — " + details
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
            "metric": "ЧДД, млрд руб",
            "baseline": f"{baseline_npv / 1e9:.3f}",
            "candidate": f"{candidate_npv / 1e9:.3f}",
            "delta": f"{delta / 1e9:+.3f}",
        },
        {
            "metric": "Прирост к базе, %",
            "baseline": "—",
            "candidate": f"{100.0 * delta / baseline_npv:+.2f}",
            "delta": "—",
        },
        {
            "metric": "Блокирующих нарушений",
            "baseline": _count_text(baseline.blocking_violations),
            "candidate": _count_text(candidate.blocking_violations),
            "delta": _delta_text(
                baseline.blocking_violations, candidate.blocking_violations
            ),
        },
        {
            "metric": "Нарушений динамики",
            "baseline": _count_text(baseline.dynamic_violations),
            "candidate": _count_text(candidate.dynamic_violations),
            "delta": _delta_text(
                baseline.dynamic_violations, candidate.dynamic_violations
            ),
        },
        {
            "metric": "Время, с",
            "baseline": f"{baseline.wallclock_seconds:.1f}",
            "candidate": f"{candidate.wallclock_seconds:.1f}",
            "delta": f"{candidate.wallclock_seconds - baseline.wallclock_seconds:+.1f}",
        },
        {
            "metric": "Прогонов OPM",
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
            "базовый ЧДД равен нулю: относительный прирост не определён, "
            "печатать проценты нечем"
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


VerifierFn = Callable[[Schedule, Path], GuardedVerification]


def _run_side(
    name: str,
    schedule: Schedule,
    work_root: Path,
    verifier: VerifierFn,
    projection: CaseLimitsOutcome | None,
) -> ComparisonSide:
    started = time.monotonic()
    guarded = verifier(schedule, work_root)
    return ComparisonSide(
        name=name,
        schedule=schedule,
        result=guarded.result,
        guard=guarded.guard,
        wallclock_seconds=time.monotonic() - started,
        opm_runs=1,
        projection=projection,
    )


def compare_baseline_to_candidate(
    *,
    run_id: str,
    case_path: Path,
    constraints: Constraints,
    baseline_schedule: Schedule,
    candidate_schedule: Schedule,
    control_dates: Sequence[date],
    forecast: ProductionForecastFn | None,
    runs_root: Path,
    model_dir: Path,
    verifier: VerifierFn | None = None,
) -> dict[str, object]:
    run_dir = Path(runs_root) / run_id
    projection = project_baseline(baseline_schedule, constraints, control_dates, forecast)
    if projection.setpoint_sum_fallback:
        raise ComparisonError(
            "проекция базы прошла по сумме уставок, а не по прогнозу отбора: "
            "такая база занижена и сравнивать с ней нельзя"
        )
    projected = projection.schedule
    baseline_deck_hash = _deck_template_hash(projected, model_dir)
    candidate_deck_hash = _deck_template_hash(candidate_schedule, model_dir)
    case_hash = constraints_hash(constraints)
    image = opm_image()

    def _default_verifier(schedule: Schedule, work_root: Path) -> GuardedVerification:
        return verify_schedule_with_guard(
            schedule,
            work_root,
            run_dir=run_dir,
            expected_schedule_hash=hash_schedule(schedule),
            expected_constraints_hash=case_hash,
            constraints=constraints,
        )

    used = verifier if verifier is not None else _default_verifier
    baseline_side = _run_side(
        "baseline", projected, run_dir / "opm-baseline", used, projection
    )
    candidate_side = _run_side(
        "candidate", candidate_schedule, run_dir / "opm-candidate", used, None
    )
    document = build_comparison_document(
        baseline_side,
        candidate_side,
        case_path=case_path,
        case_hash=case_hash,
        baseline_deck_hash=baseline_deck_hash,
        candidate_deck_hash=candidate_deck_hash,
        image=image,
        run_id=run_id,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "comparison.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document


COMPARISON_COLUMNS: tuple[str, ...] = ("metric", "baseline", "candidate", "delta")
COMPARISON_HEADER: tuple[str, ...] = ("Показатель", "База", "Кандидат", "Δ")


def print_comparison(document: dict[str, object]) -> None:
    table = document["table"]
    if not isinstance(table, list):
        raise ComparisonError("в документе сравнения нет таблицы для печати")
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


@dataclass(frozen=True, slots=True)
class ComparisonInputs:
    baseline_schedule: Schedule
    control_dates: tuple[date, ...]
    forecast: ProductionForecastFn
    model_dir: Path


def load_comparison_inputs(constraints: Constraints) -> ComparisonInputs:
    try:
        runtime = resolve_runtime_artifacts()
    except Exception as error:
        raise ComparisonError(
            "сравнение невозможно: артефакты быстрой модели недоступны, "
            f"а без них не построить оценщик отбора для проекции базы — {error}"
        ) from error
    model_dir = model_z_dir()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        scenario_ood_path=runtime.scenario_ood,
        lambda_path=LAMBDA,
        constraints=constraints,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )
    validate_runtime_economic_head(runtime, env.npv_head)
    return ComparisonInputs(
        baseline_schedule=env.base_schedule,
        control_dates=tuple(env.control_dates),
        forecast=_peak_step_production(env, make_evaluator(env)),
        model_dir=model_dir,
    )


def main() -> int:
    model_dir = model_z_dir()
    normatives_path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    runtime = resolve_runtime_artifacts()
    constraints = _load_constraints()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=normatives_path,
        response_path=RESPONSE,
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        lambda_path=LAMBDA,
        constraints=constraints,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )
    validate_runtime_economic_head(runtime, env.npv_head)
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)

    saved = json.loads(Path("data/lambda-window-2007/cmaes.json").read_text(encoding="utf-8"))
    if saved.get('schedule_path'):
        schedule = load_schedule_json(Path(saved['schedule_path']))
        repaired_prediction = evaluator(schedule)
        repair_rounds = 0
        actual_hash = hash_schedule(schedule)
        print('Проверяется сохранённый план без повторной генерации политики.', flush=True)
    else:
        theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)
        started = time.monotonic()
        final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
        schedule, repaired_prediction, _dynamic, repair_rounds = _repair_predicted_water_balance(
            env, evaluator, final.schedule
        )
        actual_hash = hash_schedule(schedule)
        print(
            f"план восстановлен из θ* за {time.monotonic() - started:.1f} с, "
            f"предсказание economic head {final.npv / 1e9:.3f} млрд, "
            f"policy-stable={final.self_consistent}, water-repair={repair_rounds}",
            flush=True,
        )
    print(f"canonical_schedule_hash: {actual_hash}", flush=True)
    expected = EXPECTED_HASH or saved["canonical_schedule_hash"]
    if actual_hash != expected:
        print(f"ХЕШ РАЗОШЁЛСЯ с записанным {expected}", flush=True)
        return 3
    print("хеш совпал с записанным в cmaes.json", flush=True)

    print("\nзвено А: эмит, прогон Flow, отклик, гейт, экономика...", flush=True)
    started = time.monotonic()
    try:
        guarded = verify_schedule_with_guard(
            schedule,
            WORK_ROOT,
            expected_schedule_hash=expected,
            constraints=constraints,
        )
    except VerificationGuardError as error:
        print(f"\n{error}", flush=True)
        return 3
    result = guarded.result
    guard = guarded.guard
    print(f"тракт отработал за {(time.monotonic() - started) / 60:.1f} мин", flush=True)

    print(f"\nстатус прогона: {result.opm_run.status}", flush=True)
    print(f"годен к сдаче (sound): {result.sound}", flush=True)
    for check in result.identities:
        mark = "OK " if check.holds else "НЕТ"
        print(f"  [{mark}] {check.name}", flush=True)
        if not check.holds:
            print(f"        {check.detail}", flush=True)
    if result.dynamic_report is not None:
        counts = {}
        for violation in result.dynamic_report.violations:
            counts[violation.kind] = counts.get(violation.kind, 0) + 1
        print(f"\nvalidate_dynamic: {len(result.dynamic_report.violations)} нарушений", flush=True)
        for kind, count in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"  {kind}: {count}", flush=True)
    if result.final_npv is not None:
        npv = result.final_npv.npv_methodology
        surrogate_npv = repaired_prediction.npv
        print(
            f"\nЧДД по настоящему прогону: {npv / 1e9:.3f} млрд "
            f"({100.0 * (npv - BASE_NPV) / BASE_NPV:+.1f}% к базовому), "
            f"предсказание economic head было {surrogate_npv / 1e9:.3f} млрд "
            f"(ошибка {100.0 * (surrogate_npv - npv) / npv:+.1f}%)",
            flush=True,
        )
    persist_observation(
        schedule,
        result,
        predicted_npv=repaired_prediction.npv,
        metadata={"candidate": "cmaes-policy", "water_repair_rounds": repair_rounds},
        guard=guard,
    )
    Path("data/g7-result.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": actual_hash,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "failed_identities": [c.name for c in result.failed_identities],
                "npv_surrogate": repaired_prediction.npv,
                "npv_opm": result.final_npv.npv_methodology if result.final_npv else None,
                "npv_baseline": BASE_NPV,
                "dynamic_violations": len(result.dynamic_report.violations)
                if result.dynamic_report
                else None,
                "verification_guard": guard.as_dict() if guard is not None else None,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print("\nитог записан: data/g7-result.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
