from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from backend.contexts.surrogate.application.pipeline.staging import (
    _build_stage,
    _snapshot,
    _manifest_status,
    _wait_for_pilot,
)
from backend.contexts.surrogate.application.pipeline.state import (
    CycleState,
    EXTRA_CONFIG,
    PILOT_CONFIG,
    _now,
)
from backend.contexts.surrogate.application.pipeline.training import (
    _record_extra,
    _train_and_finish,
)
from backend.contexts.surrogate.domain.errors import CycleError

logger = logging.getLogger("backend.contexts.surrogate.application.pipeline")


def run(args: argparse.Namespace) -> None:
    state = CycleState(args.data_root)
    if state.payload.get("phase") == "complete":
        state.event({"phase": "complete", "message": "cycle already complete"})
        return
    pilot_root = args.data_root / "dataset-main"
    extra_root = args.data_root / "dataset-extra-500"
    _wait_for_pilot(pilot_root, state, args.poll_seconds)

    state.phase("freezing_pilot_200")
    state.update_stage("pilot-200", status="compacting")
    pilot = _build_stage(
        model_dir=args.model_dir,
        root=pilot_root,
        seed=20260816,
        config=PILOT_CONFIG,
        workers=args.workers,
    )
    _snapshot(
        args.data_root / "cycle" / "pilot-200.json",
        pilot,
        pilot.samples,
        seed=20260816,
    )
    state.update_stage(
        "pilot-200",
        status="complete",
        completed=200,
        failed=0,
        dataset_hash=pilot.dataset_hash,
        plan_hash=pilot.plan_hash,
    )

    state.phase("generating_extra_500")
    state.update_stage("extra-500", status="running")
    state.update_stage(
        "combined-700", status="preparing", current_epoch=0, max_epochs=args.epochs
    )
    extra = _build_stage(
        model_dir=args.model_dir,
        root=extra_root,
        seed=20260817,
        config=EXTRA_CONFIG,
        workers=args.workers,
    )
    _record_extra(args, state, extra)
    _train_and_finish(args, state, pilot, extra)


def resume_extra(args: argparse.Namespace) -> None:
    state = CycleState(args.data_root)
    if state.payload.get("phase") == "complete":
        state.event({"phase": "complete", "message": "cycle already complete"})
        return
    state.phase("generating_extra_500")
    state.update_stage("extra-500", status="running")
    extra = _build_stage(
        model_dir=args.model_dir,
        root=args.data_root / "dataset-extra-500",
        seed=20260817,
        config=EXTRA_CONFIG,
        workers=args.workers,
    )
    _record_extra(args, state, extra)

    state.phase("loading_pilot_200")
    pilot = _build_stage(
        model_dir=args.model_dir,
        root=args.data_root / "dataset-main",
        seed=20260816,
        config=PILOT_CONFIG,
        workers=args.workers,
    )
    state.update_stage(
        "pilot-200",
        status="complete",
        completed=200,
        failed=0,
        dataset_hash=pilot.dataset_hash,
        plan_hash=pilot.plan_hash,
    )
    _train_and_finish(args, state, pilot, extra)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--resume-extra", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.resume_extra:
            resume_extra(args)
        else:
            run(args)
    except Exception as error:
        state = CycleState(args.data_root)
        message = f"{type(error).__name__}: {error}"
        state.payload["phase"] = "failed"
        state.payload["error"] = message
        state.payload["updated_at"] = _now()
        state.save()
        state.event({"phase": "failed", "error": message})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
