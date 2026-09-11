from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from backend.contexts.constraints.application.cases import CaseError, load_case
from backend.contexts.runs.application.workflow import (
    MANIFEST_PROVENANCE_FIELDS,
    RunProvenance,
    RunRequest,
    RunWorkflow,
)
from backend.contexts.runs.application.workflow import SUBMISSION_BUNDLE_FIELDS, SubmissionError
from backend.contexts.constraints.domain.constraints import Constraints
from backend.shared.paths import out_root
from backend.contexts.runs.infrastructure.provenance import git_commit
from backend.contexts.constraints.infrastructure.constraints_io import (
    constraints_from_json,
    constraints_hash,
)
from backend.contexts.economics.infrastructure.normatives_io import (
    NormativesError,
    normatives_sha256,
)
from backend.contexts.schedule.application.emit import ScheduleEmitError
from backend.contexts.simulation.infrastructure.preflight import (
    DockerPreflightError,
    ensure_docker_ready,
    resolve_image_reference,
)
from backend.shared.resources import model_z_dir, normatives_xlsx
from backend.contexts.showcase.application.run_summary import export_run_summary
from backend.contexts.reservoir.domain.horizon import HORIZON, load_horizon
from backend.interfaces.cli.runner import run as run_cli
from backend.shared.errors import ConflictError, NotFoundError, ValidationError
from backend.contexts.showcase.infrastructure.artifact_io import load_schedule_json
from backend.shared.settings import Settings
from backend.shared.json_io import read_json
from backend.contexts.optimization.application.comparison_document import (
    print_comparison,
)
from backend.contexts.optimization.application.verification_run import (
    compare_baseline_to_candidate,
)
from backend.contexts.optimization.application.verification_cli import (
    load_comparison_inputs,
)
from backend.contexts.optimization.domain.errors import ComparisonError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIOS optimisation workflow")
    parser.add_argument(
        "mode", choices=("search", "verify", "full", "submit", "compare")
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-root", type=Path, default=out_root() / "runs")
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--budget", type=int, default=None, help="number of search evaluations")
    parser.add_argument("--seed", type=int, default=None, help="seed of the independent search")
    parser.add_argument(
        "--case",
        type=Path,
        default=None,
        help="case file in Constraints format; defaults to config/competition-constraints.json",
    )
    return parser


def resolve_case(case_path: Path | None) -> Path | None:
    if case_path is None:
        return None
    try:
        load_case(case_path)
    except CaseError as error:
        raise ValidationError(
            f"case rejected - {error}", code="runs.case_rejected", path=str(case_path)
        ) from error
    return case_path


def default_case_path(settings: Settings | None = None) -> Path:
    return (Settings.from_env() if settings is None else settings).constraints_path


def resolve_constraints(case_path: Path | None) -> Constraints | None:
    if case_path is None:
        return None
    if not Path(case_path).is_file():
        return None
    try:
        return load_case(case_path)
    except CaseError as error:
        raise ValidationError(
            f"case rejected - {error}", code="runs.case_rejected", path=str(case_path)
        ) from error


def resolve_normatives_sha256() -> str | None:
    try:
        path = normatives_xlsx()
    except FileNotFoundError:
        return None
    try:
        return normatives_sha256(path)
    except NormativesError as error:
        raise ValidationError(
            f"normatives hash was not computed - {error}", code="economics.normatives"
        ) from error


def build_provenance(outcome: object, constraints: Constraints | None) -> RunProvenance:
    source = getattr(outcome, "provenance", None)
    recorded: dict[str, str] = dict(source) if isinstance(source, dict) else {}
    self_consistent = getattr(outcome, "self_consistent", None)
    evaluations = getattr(outcome, "evaluations", None)
    return RunProvenance(
        model_version=recorded.get("model_version"),
        npv_head_version=recorded.get("npv_head_version"),
        scenario_ood_version=recorded.get("scenario_ood_version"),
        feature_context_sha256=recorded.get("feature_context_sha256"),
        constraints_hash=constraints_hash(constraints) if constraints is not None else None,
        deck_hash=None,
        normatives_sha256=resolve_normatives_sha256(),
        opm_image=resolve_image_reference().image,
        git_commit=git_commit(),
        seed=recorded.get("seed"),
        search_strategy=recorded.get("search_strategy"),
        policy_equilibrium=recorded.get("policy_equilibrium"),
        iterations=evaluations if isinstance(evaluations, int) else None,
        self_consistent=self_consistent if isinstance(self_consistent, bool) else None,
    )


def load_run_request(runs_root: Path, run_id: str) -> RunRequest:
    run_dir = runs_root / run_id
    horizon_path = run_dir / "inputs" / "horizon.json"
    if horizon_path.is_file() and load_horizon(str(horizon_path)) != HORIZON:
        raise ConflictError(
            f"The process horizon differs from the saved run. "
            f"Start a new process with AIOS_HORIZON_PATH={horizon_path}",
            code="runs.horizon_mismatch",
            run_id=run_id,
        )
    request_path = run_dir / "inputs" / "request.json"
    if not request_path.is_file():
        raise NotFoundError(
            f"Run {run_id!r} not found: {request_path}",
            code="runs.not_found",
            run_id=run_id,
        )
    data = read_json(request_path)
    return RunRequest(
        run_id=run_id,
        schedule=load_schedule_json(run_dir / "schedule" / "schedule.json"),
        predicted_npv=data.get("predicted_npv"),
        constraints=load_saved_constraints(run_dir),
        provenance=load_saved_provenance(run_dir),
    )


def load_saved_provenance(run_dir: Path) -> RunProvenance:
    manifest = run_dir / "manifest.json"
    if not manifest.is_file():
        return RunProvenance()
    document = read_json(manifest)
    return RunProvenance(
        **{name: document.get(name) for name in MANIFEST_PROVENANCE_FIELDS}
    )


def load_saved_constraints(run_dir: Path) -> Constraints | None:
    saved = run_dir / "inputs" / "constraints.json"
    if not saved.is_file():
        return None
    return constraints_from_json(read_json(saved))


def require_docker() -> None:
    try:
        ensure_docker_ready()
    except DockerPreflightError as error:
        raise SystemExit(error.report.message) from error


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = args.mode
    if mode == "verify" and args.case is not None:
        raise SystemExit(
            "verify does not accept --case: the schedule of a saved run is "
            "checked together with the case it was found on"
        )
    if mode == "submit" and args.case is not None:
        raise SystemExit(
            "submit does not accept --case: the bundle is assembled from an "
            "already verified run"
        )
    if mode in {"verify", "full"}:
        require_docker()
    if mode in {"search", "full"}:
        case_path = resolve_case(args.case)
        constraints = resolve_constraints(case_path or default_case_path())
        from backend.contexts.optimization.application.search_use_case import run_search
        from backend.contexts.optimization.application.verification_run import verify_schedule

        search_options = {}
        if args.budget is not None:
            if args.budget <= 0:
                raise SystemExit("--budget must be positive")
            search_options["budget"] = args.budget
        if args.seed is not None:
            search_options["seed"] = args.seed
        outcome = run_search(case_path=case_path, **search_options)
        run_id = args.run_id or datetime.now().strftime("run-%Y%m%d-%H%M%S")
        request = RunRequest(
            run_id,
            outcome.schedule,
            outcome.predicted_npv,
            constraints=constraints,
            provenance=build_provenance(outcome, constraints),
        )
        workflow = RunWorkflow(args.runs_root)
        if mode == "search":
            manifest = workflow.search(request)
            export_run_summary(manifest, args.runs_root / run_id / "ui")
            return 0
        manifest = workflow.full(
            lambda: request,
            lambda schedule, opm_root: verify_schedule(schedule, opm_root),
        )
        export_run_summary(manifest, args.runs_root / run_id / "ui")
        return 0
    if mode == "verify":
        if not args.run_id:
            raise SystemExit("verify requires --run-id of a previously found run")
        if args.case is not None:
            raise SystemExit(
                "verify does not accept --case: the schedule of a saved run is "
                "checked together with the case it was found on"
            )
        from backend.contexts.optimization.application.verification_run import verify_schedule

        request = load_run_request(args.runs_root, args.run_id)
        workflow = RunWorkflow(args.runs_root)
        manifest = workflow.verify(request, verify_schedule)
        export_run_summary(manifest, args.runs_root / args.run_id / "ui")
        return 0
    if mode == "compare":
        if not args.run_id:
            raise SystemExit("compare requires --run-id of the run being checked")
        return compare(args.runs_root, args.run_id, args.case)
    if mode == "submit":
        if not args.run_id:
            raise SystemExit("submit requires --run-id of a verified run")
        if args.case is not None:
            raise SystemExit(
                "submit does not accept --case: the bundle is assembled from an "
                "already verified run together with the case it was found on"
            )
        return submit(args.runs_root, args.run_id, args.model_dir)
    return 0


def resolve_comparison_case(
    runs_root: Path, run_id: str, case_path: Path | None
) -> tuple[Path, Constraints]:
    run_dir = runs_root / run_id
    saved = load_saved_constraints(run_dir)
    chosen = Path(case_path) if case_path is not None else default_case_path()
    constraints = resolve_constraints(chosen)
    if constraints is None:
        if saved is None:
            raise SystemExit(
                f"comparison was not assembled - case not found in {chosen}, "
                f"nor in {run_dir / 'inputs' / 'constraints.json'}"
            )
        return run_dir / "inputs" / "constraints.json", saved
    if saved is not None and constraints_hash(saved) != constraints_hash(constraints):
        raise SystemExit(
            "comparison was not assembled - case "
            f"{chosen} diverges from the case of run {run_id}: "
            f"{constraints_hash(constraints)} against {constraints_hash(saved)}. "
            "Baseline and candidate must run under the same case"
        )
    return chosen, constraints


def compare(runs_root: Path, run_id: str, case_path: Path | None) -> int:
    chosen, constraints = resolve_comparison_case(runs_root, run_id, case_path)
    request = load_run_request(runs_root, run_id)
    try:
        inputs = load_comparison_inputs(constraints)
        document = compare_baseline_to_candidate(
            run_id=run_id,
            case_path=chosen,
            constraints=constraints,
            baseline_schedule=inputs.baseline_schedule,
            candidate_schedule=request.schedule,
            control_dates=inputs.control_dates,
            forecast=inputs.forecast,
            runs_root=runs_root,
            model_dir=inputs.model_dir,
        )
    except ComparisonError as error:
        raise SystemExit(f"comparison was not assembled - {error}") from error
    print_comparison(document)
    print(f"comparison written: {runs_root / run_id / 'comparison.json'}")
    return 0


def resolve_model_dir(model_dir: Path | None) -> Path:
    if model_dir is not None:
        return model_dir
    try:
        return model_z_dir()
    except FileNotFoundError as error:
        raise SystemExit(
            f"submission bundle was not assembled - model directory not found: {error}"
        ) from error


def submit(runs_root: Path, run_id: str, model_dir: Path | None) -> int:
    workflow = RunWorkflow(runs_root)
    try:
        report = workflow.submit(run_id, resolve_model_dir(model_dir))
    except (SubmissionError, ScheduleEmitError, FileNotFoundError) as error:
        raise SystemExit(f"submission bundle was not assembled - {error}") from error
    export_run_summary(report.manifest, runs_root / run_id / "ui")
    print(f"submission bundle: {report.directory}")
    print(f"schedule: {report.schedule_path}")
    print(f"claimed NPV, RUB: {report.bundle.claimed_npv_rub:.2f}")
    for name in SUBMISSION_BUNDLE_FIELDS:
        if name == "claimed_npv_rub":
            continue
        print(f"{name}: {getattr(report.bundle, name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
