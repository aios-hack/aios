"""One command for the real search and OPM verification scenarios.

``full`` intentionally runs both expensive stages in order. It does not treat
a fast-model prediction as a verified result.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from backend.application.cases import CaseError, load_case
from backend.application.runs import RunRequest, RunWorkflow
from backend.core.paths import out_root
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
    """Проверить файл кейса до запуска поиска: ошибка здесь дешевле."""
    if case_path is None:
        return None
    try:
        load_case(case_path)
    except CaseError as error:
        raise SystemExit(f"кейс отклонён — {error}") from error
    return case_path


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
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = args.mode
    if mode in {"search", "full"}:
        case_path = resolve_case(args.case)
        from backend.application.optimization.search_run import run_search
        from backend.application.optimization.verification_run import verify_schedule

        outcome = run_search(case_path=case_path)
        run_id = args.run_id or datetime.now().strftime("run-%Y%m%d-%H%M%S")
        request = RunRequest(run_id, outcome.schedule, outcome.predicted_npv)
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
