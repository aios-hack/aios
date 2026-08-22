"""One command for the real search and OPM verification scenarios.

``full`` intentionally runs both expensive stages in order. It does not treat
a fast-model prediction as a verified result.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from aios_backend.application.runs import RunRequest, RunWorkflow
from aios_backend.presentation.ui_export.run_summary import export_run_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIOS optimisation workflow")
    parser.add_argument("mode", choices=("search", "verify", "full"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-root", type=Path, default=Path("out/runs"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = args.mode
    if mode in {"search", "full"}:
        from aios_backend.application.optimization.search_run import run_search
        from aios_backend.application.optimization.verification_run import verify_schedule

        outcome = run_search()
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
    if mode in {"verify", "full"}:
        from aios_backend.application.optimization.verification_run import main as verify

        return verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
