from __future__ import annotations

import json
import logging
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Sequence

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.contexts.constraints.domain.schema import default_config
from backend.contexts.constraints.infrastructure.constraints_io import (
    constraints_from_json,
    constraints_hash,
)
from backend.contexts.economics.infrastructure.normatives_io import load_normatives
from backend.contexts.optimization.application.comparison_document import (
    COMPARISON_COLUMNS,
    COMPARISON_HEADER,
    COMPARISON_SCHEMA_VERSION,
    ComparisonSide,
    ConditionCheck,
    build_comparison_document,
    equal_conditions,
    print_comparison,
    project_baseline,
    refuse_unequal_conditions,
)
from backend.contexts.optimization.application.observation_store import persist_observation
from backend.contexts.optimization.application.search_use_case import CONSTRAINTS, SEED
from backend.contexts.optimization.application.verification_guard import (
    GuardCheck,
    GuardReport,
)
from backend.contexts.optimization.domain.errors import (
    ComparisonError,
    VerificationGuardError,
)
from backend.contexts.reservoir.infrastructure.opm_deck import OpmDeckEmitter
from backend.contexts.runs.infrastructure.provenance import opm_image
from backend.contexts.schedule.domain.canonical import canonical_part_hash
from backend.contexts.schedule.domain.case_limits import (
    CaseLimitsOutcome,
    ProductionForecastFn,
)
from backend.contexts.simulation.infrastructure.runner import deck_hashes, summary_spec_hash
from backend.contexts.connectivity.domain.connectivity import Groups
from backend.contexts.constraints.domain.config import ArtifactHashes
from backend.contexts.constraints.domain.constraints import Constraints, compensation_policy
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.simulation.application.submission import SubmissionResult, submit_schedule
from backend.shared.hashing import hash_schedule
from backend.shared.json_io import read_json
from backend.shared.paths import data_root
from backend.shared.resources import chdd_python_dir, model_z_dir

logger = logging.getLogger(__name__)

LAMBDA = data_root() / "lambda-window-2007/lambda.json"
RESPONSE = data_root() / "base_case/response.json"
WORK_ROOT = Path("data/g7-submission")
EXPECTED_HASH: str | None = None
BASE_NPV = 11_873_122_324.91
OIL_DENSITY_T_PER_M3 = 0.9131



def _load_constraints() -> Constraints:
    return constraints_from_json(
        read_json(CONSTRAINTS)
    )


def _read_manifest(run_dir: Path) -> dict[str, object]:
    path = run_dir / "manifest.json"
    if not path.is_file():
        return {}
    document = read_json(path)
    if not isinstance(document, dict):
        raise VerificationGuardError(
            f"the run manifest is not a JSON object: {path}"
        )
    return document


def _manifest_hash(document: dict[str, object], field: str, run_dir: Path) -> str | None:
    value = document.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise VerificationGuardError(
            f"run manifest {run_dir} contains {field}={value!r}; "
            "the reference hash must be a non-empty string"
        )
    return value


def _run_constraints_hash(run_dir: Path) -> str | None:
    path = run_dir / "inputs" / "constraints.json"
    if not path.is_file():
        return None
    document = read_json(path)
    if not isinstance(document, dict):
        raise VerificationGuardError(
            f"the saved run case is not a JSON object: {path}"
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
    schedule_source = "expected_schedule_hash argument"
    constraints_source = "expected_constraints_hash argument"
    if expected_schedule_hash is None and EXPECTED_HASH is not None:
        expected_schedule_hash = EXPECTED_HASH
        schedule_source = "EXPECTED_HASH constant"
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
        schedule_source = "reference not found"
    if expected_constraints_hash is None:
        constraints_source = "reference not found"
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
    groups: Groups | None = None,
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
    from backend.contexts.connectivity.infrastructure.groups_artifact import (
        load as load_groups,
        save as save_groups,
        build_artifact,
    )
    saved_run = _guard_run_dir(work_root, run_dir)
    groups_path = saved_run / "inputs/groups.json" if saved_run is not None else None
    if groups_path is not None and groups_path.is_file():
        recorded_groups = load_groups(groups_path).groups
        if groups is not None and groups != recorded_groups:
            raise VerificationGuardError("The supplied grouping differs from the groups saved with the run")
        groups = recorded_groups
    if groups is None and compensation_policy(used_constraints).scope == "field_and_groups":
        from backend.contexts.connectivity.domain.measure import load_lambda
        from backend.contexts.optimization.infrastructure.artifacts import resolve_lambda_selection
        selection = resolve_lambda_selection()
        artifact, _ = build_artifact(load_lambda(selection.path), extra_wells=schedule.meta.wells)
        groups = artifact.groups
        if groups_path is not None:
            groups_path.parent.mkdir(parents=True, exist_ok=True)
            save_groups(artifact, groups_path)
    for check in guard.unchecked:
        print(
            f"WARNING: {check.name} is not checked — no reference is available, "
            f"actual value {check.actual}",
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
            groups_hash=groups.group_hash if groups is not None else "0" * 64,
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
        groups=groups,
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
    groups: Groups | None = None,
) -> SubmissionResult:
    return verify_schedule_with_guard(
        schedule,
        work_root,
        run_dir=run_dir,
        expected_schedule_hash=expected_schedule_hash,
        expected_constraints_hash=expected_constraints_hash,
        constraints=constraints,
        groups=groups,
    ).result

def _deck_template_hash(schedule: Schedule, model_dir: Path) -> str:
    emitter = OpmDeckEmitter(model_dir)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        return deck_hashes(deck, schedule).deck_hash


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
            "the baseline was projected by the sum of setpoints rather than by the "
            "production forecast: such a baseline is understated and must not be "
            "compared against"
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
