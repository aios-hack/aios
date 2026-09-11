from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from backend.contexts.economics.infrastructure.normatives_io import load_normatives
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.simulation.domain.perturbation_design import (
    PerturbationFamily,
    PlanConfig,
    build_plan,
)
from backend.contexts.simulation.infrastructure.dataset import DatasetGenerator
from backend.contexts.surrogate.application.model import (
    TARGET_NAMES,
    ModelConfig,
    TrajectorySurrogate,
)
from backend.contexts.surrogate.application.train.evaluation import (
    evaluate,
    money_rub_per_unit,
)
from backend.contexts.surrogate.application.train.samples import (
    _examples,
    split_samples,
)
from backend.contexts.surrogate.domain.errors import TrainingCommandError
from backend.contexts.surrogate.infrastructure.model_z_context import (
    build_model_z_context,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--level-scenarios", type=int, default=110)
    parser.add_argument("--unreachable-scenarios", type=int, default=40)
    parser.add_argument("--shutdown-scenarios", type=int, default=35)
    parser.add_argument("--conversion-scenarios", type=int, default=14)
    parser.add_argument("--validation-fraction", type=float, default=0.15)
    parser.add_argument("--test-fraction", type=float, default=0.15)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=32768)
    parser.add_argument("--hidden-width", type=int, default=128)
    parser.add_argument("--hidden-layers", type=int, default=3)
    parser.add_argument("--device", default=None)
    parser.add_argument("--oil-density", type=float, default=0.9131)
    parser.add_argument("--money-loss-alpha", type=float, default=0.7)
    parser.add_argument("--money-weight-cap", type=float, default=50.0)
    parser.add_argument("--lr-schedule", choices=("none", "cosine"), default="none")
    parser.add_argument("--select-by", choices=("loss", "money", "rank"), default="loss")
    parser.add_argument(
        "--target-parameterization",
        choices=("absolute", "watercut"),
        default="watercut",
        help="watercut is the contract target set: oil is derived from liquid "
             "and watercut rather than predicted independently (§5.1)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.oil_density <= 0.0:
        raise TrainingCommandError("oil-density must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generator = DatasetGenerator(
        args.model_dir,
        args.dataset_root,
        max_workers=args.workers,
        timeout_seconds=7200.0,
        compact_artifacts=True,
    )
    config = PlanConfig(
        n_level_scenarios=args.level_scenarios,
        n_unreachable_scenarios=args.unreachable_scenarios,
        n_shutdown_scenarios=args.shutdown_scenarios,
        n_conversion_scenarios=args.conversion_scenarios,
    )
    plan = build_plan(generator.base_schedule(), seed=args.seed, config=config)
    print(
        json.dumps({"phase": "load_dataset", "n_scenarios": len(plan.specs)}),
        flush=True,
    )
    dataset = generator.build(plan)
    samples = tuple(
        sample
        for sample in dataset.samples
        if sample.response is not None and sample.metadata.response_hash
    )
    if dataset.failed or dataset.skipped or len(samples) != len(plan.specs):
        raise TrainingCommandError(
            f"the dataset is incomplete: samples={len(samples)}, plan={len(plan.specs)}, "
            f"failed={len(dataset.failed)}, skipped={len(dataset.skipped)}"
        )
    split = split_samples(
        samples,
        validation_fraction=args.validation_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    print(
        json.dumps(
            {
                "phase": "build_context",
                "train": len(split.train),
                "validation": len(split.validation),
                "test": len(split.test),
            }
        ),
        flush=True,
    )
    context = build_model_z_context(
        args.model_dir, split.train, dataset_hash=dataset.dataset_hash
    )
    context.save(args.output_dir / "feature_context.json")
    train = _examples(split.train, context)
    validation = _examples(split.validation, context)
    test = _examples(split.test, context)
    settings = ModelConfig(
        hidden_width=args.hidden_width,
        hidden_layers=args.hidden_layers,
        batch_size=args.batch_size,
        max_epochs=args.epochs,
        patience=args.patience,
        seed=args.seed,
        money_rub_per_unit=money_rub_per_unit(load_normatives(args.normatives)),
        money_weight_alpha=args.money_loss_alpha,
        money_weight_cap=args.money_weight_cap,
        lr_schedule=args.lr_schedule,
        select_by=args.select_by,
        target_parameterization=args.target_parameterization,
        oil_density_t_per_m3=args.oil_density,
    )
    result = TrajectorySurrogate.fit(
        train,
        validation,
        config=settings,
        dataset_hash=dataset.dataset_hash,
        device=args.device,
        epoch_callback=lambda item: print(
            json.dumps({"phase": "train", **asdict(item)}), flush=True
        ),
    )
    checkpoint = result.model.save(args.output_dir / "model.pt")
    print(json.dumps({"phase": "evaluate", "n_test": len(test)}), flush=True)
    metrics = evaluate(
        result.model,
        test,
        split.test,
        context,
        model_schedule_path=args.model_dir / "Model_Z_sch.inc",
        normatives_path=args.normatives,
        oil_density_t_per_m3=args.oil_density,
    )
    report = {
        "format": "aios.surrogate-training-report.v1",
        "loss_weighting": {
            "money_rub_per_unit": dict(
                zip(TARGET_NAMES, settings.money_rub_per_unit)
            ),
            "money_weight_alpha": settings.money_weight_alpha,
            "money_weight_cap": settings.money_weight_cap,
            "lr_schedule": settings.lr_schedule,
            "select_by": settings.select_by,
            "target_parameterization": settings.target_parameterization,
        },
        "dataset_hash": dataset.dataset_hash,
        "plan_hash": dataset.plan_hash,
        "model_version": result.model.version,
        "checkpoint": checkpoint.name,
        "feature_context": "feature_context.json",
        "seed": args.seed,
        "split": {
            "train": [item.metadata.scenario_id for item in split.train],
            "validation": [item.metadata.scenario_id for item in split.validation],
            "test": [item.metadata.scenario_id for item in split.test],
        },
        "families": {
            family.value: sum(item.metadata.family is family for item in samples)
            for family in PerturbationFamily
        },
        "best_epoch": result.best_epoch,
        "history": [asdict(item) for item in result.history],
        "metrics": metrics,
    }
    report_path = args.output_dir / "training_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "checkpoint": str(checkpoint),
                "report": str(report_path),
                "model_version": result.model.version,
                "spearman": metrics["ranking"]["spearman_rank_correlation"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
