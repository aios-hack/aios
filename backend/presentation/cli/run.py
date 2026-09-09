from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from backend.application.cases import CaseError, load_case
from backend.application.runs import RunProvenance, RunRequest, RunWorkflow
from backend.core.contracts import Constraints
from backend.core.paths import out_root
from backend.core.provenance import git_commit, opm_image
from backend.domain.configuration.constraints_io import constraints_from_json, constraints_hash
from backend.domain.economics.normatives_io import NormativesError, normatives_sha256
from backend.infrastructure.resources import normatives_xlsx
from backend.presentation.ui_export.run_summary import export_run_summary
from backend.presentation.ui_export.artifact_io import load_schedule_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIOS optimisation workflow")
    parser.add_argument("mode", choices=("search", "verify", "full"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-root", type=Path, default=out_root() / "runs")
    parser.add_argument(
        "--case",
        type=Path,
        default=None,
        help="файл кейса в формате Constraints; по умолчанию config/competition-constraints.json",
    )
    return parser


def resolve_case(case_path: Path | None) -> Path | None:
    if case_path is None:
        return None
    try:
        load_case(case_path)
    except CaseError as error:
        raise SystemExit(f"кейс отклонён — {error}") from error
    return case_path


def default_case_path() -> Path:
    return Path(
        os.environ.get("AIOS_CONSTRAINTS_PATH", "config/competition-constraints.json")
    )


def resolve_constraints(case_path: Path | None) -> Constraints | None:
    if case_path is None:
        return None
    if not Path(case_path).is_file():
        return None
    try:
        return load_case(case_path)
    except CaseError as error:
        raise SystemExit(f"кейс отклонён — {error}") from error


def resolve_normatives_sha256() -> str | None:
    try:
        path = normatives_xlsx()
    except FileNotFoundError:
        return None
    try:
        return normatives_sha256(path)
    except NormativesError as error:
        raise SystemExit(f"хеш нормативов не посчитан — {error}") from error


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
        opm_image=opm_image(),
        git_commit=git_commit(),
        seed=recorded.get("seed"),
        search_strategy=recorded.get("search_strategy"),
        policy_equilibrium=recorded.get("policy_equilibrium"),
        iterations=evaluations if isinstance(evaluations, int) else None,
        self_consistent=self_consistent if isinstance(self_consistent, bool) else None,
    )


def load_run_request(runs_root: Path, run_id: str) -> RunRequest:
    run_dir = runs_root / run_id
    request_path = run_dir / "inputs" / "request.json"
    if not request_path.is_file():
        raise SystemExit(f"Запуск {run_id!r} не найден: {request_path}")
    data = json.loads(request_path.read_text(encoding="utf-8"))
    return RunRequest(
        run_id=run_id,
        schedule=load_schedule_json(run_dir / "schedule" / "schedule.json"),
        predicted_npv=data.get("predicted_npv"),
        constraints=load_saved_constraints(run_dir),
    )


def load_saved_constraints(run_dir: Path) -> Constraints | None:
    saved = run_dir / "inputs" / "constraints.json"
    if not saved.is_file():
        return None
    return constraints_from_json(json.loads(saved.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = args.mode
    if mode in {"search", "full"}:
        case_path = resolve_case(args.case)
        constraints = resolve_constraints(case_path or default_case_path())
        from backend.application.optimization.search_run import run_search
        from backend.application.optimization.verification_run import verify_schedule

        outcome = run_search(case_path=case_path)
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
            raise SystemExit("verify требует --run-id ранее найденного запуска")
        if args.case is not None:
            raise SystemExit(
                "verify не принимает --case: проверяется расписание сохранённого "
                "запуска вместе с кейсом, на котором оно было найдено"
            )
        from backend.application.optimization.verification_run import verify_schedule

        request = load_run_request(args.runs_root, args.run_id)
        workflow = RunWorkflow(args.runs_root)
        manifest = workflow.verify(request, verify_schedule)
        export_run_summary(manifest, args.runs_root / args.run_id / "ui")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
