"""Durable two-stage Model_Z cycle: freeze 200, add 500, train on 700."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from backend.infrastructure.opm.dataset import DatasetBuildReport, DatasetGenerator, DatasetSample
from backend.infrastructure.opm.dataset_plan import PlanConfig, PerturbationFamily, build_plan
from backend.core.contracts import canonical_bytes

from .model import ModelConfig, TrajectorySurrogate
from .model_z_context import build_model_z_context
from .train import _examples, evaluate, split_samples


PILOT_CONFIG = PlanConfig(
    n_level_scenarios=110,
    n_unreachable_scenarios=40,
    n_shutdown_scenarios=35,
    n_conversion_scenarios=14,
)
EXTRA_CONFIG = PlanConfig(
    n_level_scenarios=275,
    n_unreachable_scenarios=100,
    n_shutdown_scenarios=87,
    n_conversion_scenarios=37,
)


class CycleError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CycleState:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.path = data_root / "cycle.json"
        self.events_path = data_root / "cycle-events.jsonl"
        default: dict[str, Any] = {
            "format": "aios.model-z-cycle.v1",
            "updated_at": _now(),
            "phase": "waiting_pilot",
            "stages": [
                {
                    "id": "pilot-200",
                    "title": "Пилот 200",
                    "dataset_root": "dataset-main",
                    "target": 200,
                    "seed": 20260816,
                    "status": "running",
                    "snapshot": "cycle/pilot-200.json",
                },
                {
                    "id": "extra-500",
                    "title": "Расширение 500",
                    "dataset_root": "dataset-extra-500",
                    "target": 500,
                    "seed": 20260817,
                    "status": "queued",
                    "snapshot": "cycle/extra-500.json",
                },
                {
                    "id": "combined-700",
                    "title": "Итого 700",
                    "dataset_root": "",
                    "target": 700,
                    "status": "queued",
                    "report": "model-task34-700/training_report.json",
                },
            ],
        }
        self.data_root.mkdir(parents=True, exist_ok=True)
        (self.data_root / "cycle").mkdir(parents=True, exist_ok=True)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = None
        self.payload = (
            loaded
            if isinstance(loaded, dict)
            and loaded.get("format") == "aios.model-z-cycle.v1"
            else default
        )
        self.save()

    def stage(self, stage_id: str) -> dict[str, Any]:
        return next(item for item in self.payload["stages"] if item["id"] == stage_id)

    def update_stage(self, stage_id: str, **changes: Any) -> None:
        self.stage(stage_id).update(changes)
        self.payload["updated_at"] = _now()
        self.save()

    def phase(self, value: str) -> None:
        self.payload["phase"] = value
        if value != "failed":
            self.payload.pop("error", None)
        self.payload["updated_at"] = _now()
        self.save()
        self.event({"phase": value})

    def event(self, payload: dict[str, Any]) -> None:
        row = {"at": _now(), **payload}
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        print(json.dumps(row, ensure_ascii=False, allow_nan=False), flush=True)

    def save(self) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _manifest_status(root: Path) -> tuple[int, int]:
    latest: dict[str, dict[str, Any]] = {}
    try:
        lines = (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0, 0
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        scenario_id = str(row.get("scenario_id", ""))
        if scenario_id:
            latest[scenario_id] = row
    successful = sum(row.get("status") == "OK" for row in latest.values())
    failed = len(latest) - successful
    return successful, failed


def _wait_for_pilot(root: Path, state: CycleState, poll_seconds: int) -> None:
    last = -1
    while True:
        successful, failed = _manifest_status(root)
        if successful != last:
            state.update_stage("pilot-200", completed=successful, failed=failed)
            state.event(
                {
                    "phase": "waiting_pilot",
                    "stage": "pilot-200",
                    "completed": successful,
                    "target": 200,
                    "failed": failed,
                }
            )
            last = successful
        if failed:
            raise CycleError(f"пилот содержит {failed} неуспешных сценариев")
        if successful >= 200:
            return
        time.sleep(poll_seconds)


def _generator(
    model_dir: Path,
    root: Path,
    *,
    workers: int,
) -> DatasetGenerator:
    return DatasetGenerator(
        model_dir,
        root,
        max_workers=workers,
        timeout_seconds=7200.0,
        load_responses=True,
        compact_artifacts=True,
    )


def _build_stage(
    *,
    model_dir: Path,
    root: Path,
    seed: int,
    config: PlanConfig,
    workers: int,
) -> DatasetBuildReport:
    generator = _generator(model_dir, root, workers=workers)
    plan = build_plan(generator.base_schedule(), seed=seed, config=config)
    report = generator.build(plan)
    if report.failed or report.skipped or len(report.samples) != len(plan.specs):
        raise CycleError(
            f"этап {root.name} неполон: samples={len(report.samples)}, "
            f"plan={len(plan.specs)}, failed={len(report.failed)}, "
            f"skipped={len(report.skipped)}"
        )
    return report


def _snapshot(
    path: Path,
    report: DatasetBuildReport,
    samples: Sequence[DatasetSample],
    *,
    seed: int,
) -> None:
    payload = {
        "format": "aios.dataset-stage-snapshot.v1",
        "created_at": _now(),
        "dataset_hash": report.dataset_hash,
        "plan_hash": report.plan_hash,
        "seed": seed,
        "n_scenarios": len(samples),
        "families": {
            family.value: sum(item.metadata.family is family for item in samples)
            for family in PerturbationFamily
        },
        "scenarios": [
            {
                "scenario_id": item.metadata.scenario_id,
                "family": item.metadata.family.value,
                "canonical_schedule_hash": item.metadata.canonical_schedule_hash,
                "response_hash": item.metadata.response_hash,
                "run_id": item.metadata.run_id,
                "wallclock_seconds": item.metadata.wallclock_seconds,
            }
            for item in samples
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _combined_hash(pilot: DatasetBuildReport, extra: DatasetBuildReport) -> str:
    payload = {
        "format": "aios.combined-dataset.v1",
        "dataset_hashes": [pilot.dataset_hash, extra.dataset_hash],
        "plan_hashes": [pilot.plan_hash, extra.plan_hash],
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _train_combined(
    *,
    model_dir: Path,
    normatives: Path,
    output_dir: Path,
    pilot: DatasetBuildReport,
    extra: DatasetBuildReport,
    state: CycleState,
    seed: int,
    epochs: int,
    patience: int,
) -> dict[str, Any]:
    samples = tuple(pilot.samples) + tuple(extra.samples)
    dataset_hash = _combined_hash(pilot, extra)
    state.phase("splitting_700")
    split = split_samples(
        samples,
        validation_fraction=0.15,
        test_fraction=0.15,
        seed=seed,
    )
    state.phase("building_context_700")
    context = build_model_z_context(
        model_dir, split.train, dataset_hash=dataset_hash
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    context.save(output_dir / "feature_context.json")
    state.phase("featureizing_700")
    train = _examples(split.train, context)
    validation = _examples(split.validation, context)
    test = _examples(split.test, context)
    settings = ModelConfig(
        hidden_width=128,
        hidden_layers=3,
        batch_size=32768,
        max_epochs=epochs,
        patience=patience,
        seed=seed,
    )

    best_validation_loss = float("inf")
    best_epoch = 0

    def on_epoch(item) -> None:
        nonlocal best_epoch, best_validation_loss
        if item.validation_loss < best_validation_loss:
            best_validation_loss = item.validation_loss
            best_epoch = item.epoch
        state.update_stage(
            "combined-700",
            current_epoch=item.epoch,
            max_epochs=epochs,
            best_epoch=best_epoch,
            train_loss=item.train_loss,
            validation_loss=item.validation_loss,
            best_validation_loss=best_validation_loss,
        )
        state.event({"phase": "train", **asdict(item)})

    state.phase("training_combined_700")
    result = TrajectorySurrogate.fit(
        train,
        validation,
        config=settings,
        dataset_hash=dataset_hash,
        device="cpu",
        epoch_callback=on_epoch,
    )
    checkpoint = result.model.save(output_dir / "model.pt")
    state.phase("evaluating_700")
    metrics = evaluate(
        result.model,
        test,
        split.test,
        context,
        model_schedule_path=model_dir / "Model_Z_sch.inc",
        normatives_path=normatives,
        oil_density_t_per_m3=0.9131,
    )
    report = {
        "format": "aios.surrogate-combined-training-report.v1",
        "dataset_hash": dataset_hash,
        "source_dataset_hashes": [pilot.dataset_hash, extra.dataset_hash],
        "source_plan_hashes": [pilot.plan_hash, extra.plan_hash],
        "model_version": result.model.version,
        "checkpoint": checkpoint.name,
        "feature_context": "feature_context.json",
        "seed": seed,
        "split": {
            "train": len(split.train),
            "validation": len(split.validation),
            "test": len(split.test),
        },
        "best_epoch": result.best_epoch,
        "history": [asdict(item) for item in result.history],
        "metrics": metrics,
        "target_rows": result.target_rows,
        "backflow_intervals": result.backflow_intervals,
        "backflow_worst_tonnes": result.backflow_worst_tonnes,
    }
    (output_dir / "training_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def _record_extra(
    args: argparse.Namespace,
    state: CycleState,
    extra: DatasetBuildReport,
) -> None:
    _snapshot(
        args.data_root / "cycle" / "extra-500.json",
        extra,
        extra.samples,
        seed=20260817,
    )
    state.update_stage(
        "extra-500",
        status="complete",
        completed=500,
        failed=0,
        dataset_hash=extra.dataset_hash,
        plan_hash=extra.plan_hash,
    )


def _train_and_finish(
    args: argparse.Namespace,
    state: CycleState,
    pilot: DatasetBuildReport,
    extra: DatasetBuildReport,
) -> None:
    state.phase("preparing_training_700")
    state.update_stage(
        "combined-700",
        status="training",
        current_epoch=0,
        max_epochs=args.epochs,
        training_started_at=_now(),
    )
    report = _train_combined(
        model_dir=args.model_dir,
        normatives=args.normatives,
        output_dir=args.data_root / "model-task34-700",
        pilot=pilot,
        extra=extra,
        state=state,
        seed=20260817,
        epochs=args.epochs,
        patience=args.patience,
    )
    state.update_stage(
        "combined-700",
        status="complete",
        completed=700,
        dataset_hash=report["dataset_hash"],
        model_version=report["model_version"],
        best_epoch=report["best_epoch"],
    )
    state.phase("complete")


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
    """Resume the live 500-stage first, without retaining pilot data in RAM.

    This path is used when increasing OPM parallelism mid-stage.  It reloads
    the already compacted pilot only after all Flow containers have exited,
    leaving the maximum possible RAM headroom for the simulation workers.
    """

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
