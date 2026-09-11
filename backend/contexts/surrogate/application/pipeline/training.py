from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend.contexts.simulation.infrastructure.dataset import DatasetBuildReport
from backend.contexts.surrogate.application.model import ModelConfig, TrajectorySurrogate
from backend.contexts.surrogate.application.pipeline.staging import (
    _combined_hash,
    _snapshot,
)
from backend.contexts.surrogate.application.pipeline.state import CycleState, _now
from backend.contexts.surrogate.application.train import _examples, evaluate, split_samples
from backend.contexts.surrogate.domain.errors import CycleError
from backend.contexts.surrogate.infrastructure.model_z_context import build_model_z_context

logger = logging.getLogger("backend.contexts.surrogate.application.pipeline")


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


__all__ = [
    "_record_extra",
    "_train_and_finish",
    "_train_combined",
]
