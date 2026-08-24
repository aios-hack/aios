"""Reproducible task-34 training entry point for the real Model_Z dataset.

The command reconstructs the versioned perturbation plan, loads successful
OPM responses through :class:`bridge.dataset.DatasetGenerator`, performs a
scenario-level split, estimates lambda strictly on the training split, and
trains the full-trajectory neural surrogate.  The held-out report contains
real-unit target errors, OOD diagnostics, NPV ranking, watercut, and the
money-producing ``StateAtDate`` metrics.  It never labels synthetic data as
a quality measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence

from bridge.dataset import DatasetGenerator, DatasetSample
from bridge.dataset_plan import PlanConfig, PerturbationFamily, build_plan
from config.schema import default_policies
from contracts import NormativeSet, ResponseArtifact, canonical_bytes
from economics import analyze_base_case, load_normatives
from schedule import parse_schedule

from .adapter import ResponseAdapter
from .features import ScheduleFeatureizer
from .metrics import WellTrajectory, ranking_metrics, state_metrics, watercut_metrics
from .model import (
    TARGET_NAMES,
    ModelConfig,
    TrainingExample,
    TrajectorySurrogate,
    target_mae,
)
from .model_z_context import ModelZFeatureArtifact, build_model_z_context


class TrainingCommandError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Split:
    train: tuple[DatasetSample, ...]
    validation: tuple[DatasetSample, ...]
    test: tuple[DatasetSample, ...]


def split_samples(
    samples: Sequence[DatasetSample],
    *,
    validation_fraction: float,
    test_fraction: float,
    seed: int,
) -> Split:
    """Split whole scenarios before any response-derived context is fit."""

    if len(samples) < 8:
        raise TrainingCommandError("для train/validation/test нужно хотя бы 8 прогонов")
    if not (0.0 < validation_fraction < 1.0 and 0.0 < test_fraction < 1.0):
        raise TrainingCommandError("доли validation/test должны лежать в (0, 1)")
    if validation_fraction + test_fraction >= 1.0:
        raise TrainingCommandError("доли validation/test не оставляют train split")
    order = list(range(len(samples)))
    random.Random(seed).shuffle(order)
    n_test = max(1, round(len(samples) * test_fraction))
    n_validation = max(1, round(len(samples) * validation_fraction))
    test_ids = set(order[:n_test])
    validation_ids = set(order[n_test : n_test + n_validation])
    train = tuple(
        sample
        for index, sample in enumerate(samples)
        if index not in test_ids and index not in validation_ids
    )
    validation = tuple(
        sample for index, sample in enumerate(samples) if index in validation_ids
    )
    test = tuple(sample for index, sample in enumerate(samples) if index in test_ids)
    if len(train) < 8:
        raise TrainingCommandError("train split слишком мал для независимой оценки lambda")
    return Split(train=train, validation=validation, test=test)


def _examples(
    samples: Iterable[DatasetSample], artifact: ModelZFeatureArtifact
) -> tuple[TrainingExample, ...]:
    featureizer = ScheduleFeatureizer()
    result: list[TrainingExample] = []
    for sample in samples:
        if sample.response is None:
            raise TrainingCommandError(
                f"сценарий {sample.metadata.scenario_id} не содержит ResponseArtifact"
            )
        # Per-edge lambda rows are already aggregated into the two neighbour
        # features on every node.  The current node MLP does not consume the
        # raw edge list; dropping it avoids retaining tens of millions of
        # redundant Python objects for a 200-scenario Model_Z dataset.
        model_input = replace(
            featureizer.transform(sample.schedule, artifact.context),
            lambda_edges=(),
        )
        result.append(
            TrainingExample(
                input=model_input,
                response=sample.response,
            )
        )
    return tuple(result)


def _evaluation_artifact(
    model_version: str,
    sample: DatasetSample,
    predicted_states: tuple,
    predicted_intervals: tuple,
) -> ResponseArtifact:
    identity = {
        "model_version": model_version,
        "scenario_id": sample.metadata.scenario_id,
        "schedule_hash": sample.metadata.canonical_schedule_hash,
    }
    return ResponseArtifact(
        source_run_id=f"surrogate-evaluation:{model_version[:12]}",
        response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
        state_at_date=predicted_states,
        interval_response=predicted_intervals,
    )


def _trajectories(artifact: ResponseArtifact) -> tuple[WellTrajectory, ...]:
    states: dict[str, list] = {}
    responses: dict[str, list] = {}
    for item in artifact.state_at_date:
        states.setdefault(item.well, []).append(item)
    for item in artifact.interval_response:
        responses.setdefault(item.well, []).append(item)
    if set(states) != set(responses):
        raise TrainingCommandError("оси StateAtDate и IntervalResponse разошлись")
    return tuple(
        WellTrajectory(
            well=well,
            states=tuple(sorted(states[well], key=lambda item: item.deck_date_index)),
            responses=tuple(
                sorted(responses[well], key=lambda item: item.control_step)
            ),
        )
        for well in sorted(states)
    )


def _mean_dict(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        raise TrainingCommandError("нельзя усреднить пустой список метрик")
    return {
        key: mean(float(row[key]) for row in rows)
        for key in rows[0]
        if isinstance(rows[0][key], (int, float)) and not isinstance(rows[0][key], bool)
    }


def evaluate(
    model: TrajectorySurrogate,
    examples: Sequence[TrainingExample],
    samples: Sequence[DatasetSample],
    context: ModelZFeatureArtifact,
    *,
    model_schedule_path: Path,
    normatives_path: Path | None = None,
    normatives: NormativeSet | None = None,
    oil_density_t_per_m3: float,
) -> dict[str, Any]:
    if len(examples) != len(samples) or len(examples) < 2:
        raise TrainingCommandError("для ranking нужны совпадающие test-наборы >= 2")
    if (normatives_path is None) == (normatives is None):
        raise TrainingCommandError("задайте ровно один источник нормативов")
    parsed = parse_schedule(model_schedule_path.read_bytes())
    if normatives is None:
        normatives = load_normatives(normatives_path)
    policies = default_policies()
    adapter = ResponseAdapter()
    actual_npv: list[float] = []
    predicted_npv: list[float] = []
    state_rows: list[dict[str, Any]] = []
    watercut_rows: list[dict[str, Any]] = []
    ood_scores: list[float] = []
    ood_exceedances = 0

    for example, sample in zip(examples, samples):
        if sample.response is None:
            raise TrainingCommandError("test sample без отклика")
        scored = model.predict(example.input)
        ood_scores.append(scored.ood.score)
        ood_exceedances += len(scored.ood.exceedances)
        states, intervals = adapter.adapt(
            scored.output,
            sample.schedule,
            sample.response,
            context.context.control_dates,
        )
        predicted = _evaluation_artifact(
            model.version, sample, states, intervals
        )
        actual_npv.append(
            analyze_base_case(
                sample.response,
                parsed.dates,
                parsed.t0_deck_date_index,
                normatives,
                policies,
            ).npv_methodology
        )
        predicted_npv.append(
            analyze_base_case(
                predicted,
                parsed.dates,
                parsed.t0_deck_date_index,
                normatives,
                policies,
            ).npv_methodology
        )
        state_rows.append(
            asdict(
                state_metrics(
                    _trajectories(predicted),
                    _trajectories(sample.response),
                    normatives=normatives,
                    policies=policies,
                )
            )
        )
        watercut_rows.append(
            asdict(
                watercut_metrics(
                    sample.response.interval_response,
                    predicted.interval_response,
                    oil_density_t_per_m3=oil_density_t_per_m3,
                )
            )
        )

    finite_ood = [value for value in ood_scores if math.isfinite(value)]
    return {
        "target_mae": target_mae(model, examples),
        "ranking": asdict(ranking_metrics(actual_npv, predicted_npv)),
        "state_mean_per_scenario": _mean_dict(state_rows),
        "watercut_mean_per_scenario": _mean_dict(watercut_rows),
        "ood": {
            "n_scenarios": len(ood_scores),
            "n_scenarios_outside": sum(value > 0.0 for value in ood_scores),
            "n_exceedances": ood_exceedances,
            "max_finite_score": max(finite_ood, default=0.0),
            "n_infinite_scores": sum(not math.isfinite(value) for value in ood_scores),
        },
        "actual_npv_rub": actual_npv,
        "predicted_npv_rub": predicted_npv,
        "synthetic_inputs": False,
    }


def money_rub_per_unit(normatives: NormativeSet) -> tuple[float, ...]:
    """₽ на физическую единицу для каждой цели, в порядке TARGET_NAMES.

    Коэффициенты сняты напрямую с economics/npv.py build_cell_flows: выручка,
    вычеты и opex по нефти линейны по oil_mass_t, opex жидкости — по
    liquid_volume_m3, opex закачки — по injection_volume_m3. Дебиты и забойное
    давление ни в одну денежную статью не входят и получают ноль: они нужны
    модели ради физики и режимных голов, но рублёвой цены ошибки не имеют.
    """
    linear = {
        "oil_mass_delta": (
            normatives.price_oil_rub_per_t
            - normatives.deductions_rub_per_t
            - normatives.opex_oil_rub_per_t
        ),
        "liquid_volume_delta": -normatives.opex_liquid_rub_per_t,
        "injection_volume_delta": -normatives.opex_injection_rub_per_m3,
    }
    return tuple(float(linear.get(name, 0.0)) for name in TARGET_NAMES)


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
    # Прежние 80 эпох с терпением 10 обрывали обучение задолго до сходимости:
    # лучшая эпоха оказывалась на 250-330 из 400 при терпении 100.
    parser.add_argument("--epochs", type=int, default=600)
    parser.add_argument("--patience", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=32768)
    parser.add_argument("--hidden-width", type=int, default=128)
    parser.add_argument("--hidden-layers", type=int, default=3)
    parser.add_argument("--device", default=None)
    parser.add_argument("--oil-density", type=float, default=0.9131)
    parser.add_argument("--money-loss-alpha", type=float, default=0.7)
    parser.add_argument("--money-weight-cap", type=float, default=50.0)
    parser.add_argument("--lr-schedule", choices=("none", "cosine"), default="none")
    parser.add_argument("--select-by", choices=("loss", "money", "rank"), default="loss")
    # Замерено на 700 прогонах: связка сценарной сводки, попарного рангового
    # члена и длинного обучения даёт Spearman 0.733 ± 0.010 по трём сидам
    # против 0.526 у прежних настроек, сжатие разброса ЧДД 0.95 против 0.27, а
    # различающий шум падает вдвое. Порознь ни один из трёх ничего не давал.
    parser.add_argument("--scenario-context", choices=("none", "mean", "rich"),
                        default="mean")
    parser.add_argument("--ranking-loss-weight", type=float, default=4.0)
    parser.add_argument(
        "--target-parameterization",
        choices=("absolute", "watercut"),
        default="watercut",
        help="watercut — контрактный набор целей: нефть выводится из жидкости "
             "и обводнённости, а не предсказывается независимо (§5.1)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.oil_density <= 0.0:
        raise TrainingCommandError("oil-density должна быть положительной")
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
            f"датасет неполон: samples={len(samples)}, plan={len(plan.specs)}, "
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
        money_weight_cap=args.money_weight_cap,
        lr_schedule=args.lr_schedule,
        target_parameterization=args.target_parameterization,
        oil_density_t_per_m3=args.oil_density,
        scenario_context=(
            False if args.scenario_context == "none" else args.scenario_context
        ),
        ranking_loss_weight=args.ranking_loss_weight,
        money_rub_per_unit=(
            money_rub_per_unit(load_normatives(args.normatives))
            if args.ranking_loss_weight > 0.0
            else ()
        ),
        money_weight_alpha=0.0,
        select_by="rank" if args.ranking_loss_weight > 0.0 else args.select_by,
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
