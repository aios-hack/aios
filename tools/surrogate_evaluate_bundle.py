"""Evaluate production surrogate checkpoints on one exact cached split.

The command is deliberately cache-only: a missing OPM result aborts the run
instead of silently launching Flow.  Validation is evaluated before test so
that all affine NPV calibrations are fitted without test leakage.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import shutil
import statistics
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from bridge.dataset import DatasetGenerator, DatasetSample, RunMetadata
from bridge.dataset_plan import build_plan
from bridge.response_loader import ResponseLoader, load_density_by_pvtnum
from bridge.runner import deck_hashes
from contracts import RunStatus, hash_schedule
from economics import load_normatives
from surrogate.cycle import EXTRA_CONFIG, PILOT_CONFIG
from surrogate.metrics import ranking_metrics
from surrogate.model import TrajectorySurrogate
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.npv_calibration import (
    NpvCalibration,
    calibration_metrics,
    fit_npv_calibration,
)
from surrogate.train import _examples, evaluate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--split-report", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--rank-checkpoint", type=Path, required=True)
    parser.add_argument("--physical-checkpoint", type=Path, required=True)
    parser.add_argument("--published-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oil-density", type=float, default=0.9131)
    return parser


def _log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def _materials(model_dir: Path, data_root: Path):
    result = {}
    for name, seed, config in (
        ("dataset-main", 20260816, PILOT_CONFIG),
        ("dataset-extra-500", 20260817, EXTRA_CONFIG),
    ):
        generator = DatasetGenerator(
            model_dir,
            data_root / name,
            max_workers=1,
            timeout_seconds=1.0,
            compact_artifacts=False,
            load_responses=False,
        )
        accepted, skipped = generator.prepare(
            build_plan(generator.base_schedule(), seed=seed, config=config)
        )
        if skipped:
            raise RuntimeError(f"{name}: статически отсеяно {len(skipped)} сценариев")
        for material in accepted:
            key = (name, material.spec.scenario_id)
            if key in result:
                raise RuntimeError(f"дублирующийся сценарий {key}")
            result[key] = material
    if len(result) != 700:
        raise RuntimeError(f"ожидалось 700 сценариев, получено {len(result)}")
    return result


def _load_cached_samples(
    identities: list[dict[str, str]],
    *,
    materials,
    model_dir: Path,
    data_root: Path,
) -> tuple[DatasetSample, ...]:
    samples = []
    loader = ResponseLoader()
    densities = load_density_by_pvtnum(model_dir)
    with tempfile.TemporaryDirectory(prefix="aios-surrogate-eval-") as temporary:
        temporary_root = Path(temporary)
        generators = {
            name: DatasetGenerator(
                model_dir,
                temporary_root / name,
                cache_root=data_root / name / "cache",
                max_workers=1,
                timeout_seconds=1.0,
                compact_artifacts=False,
                load_responses=False,
            )
            for name in ("dataset-main", "dataset-extra-500")
        }
        for index, identity in enumerate(identities, start=1):
            source = identity["source_dataset"]
            scenario_id = identity["scenario_id"]
            material = materials[(source, scenario_id)]
            expected_schedule_hash = identity["canonical_schedule_hash"]
            actual_schedule_hash = hash_schedule(material.schedule)
            if actual_schedule_hash != expected_schedule_hash:
                raise RuntimeError(
                    f"{source}:{scenario_id}: schedule hash изменился: "
                    f"{actual_schedule_hash} != {expected_schedule_hash}"
                )

            generator = generators[source]
            deck = generator.emit_deck(material)
            hashes = deck_hashes(deck, material.schedule)
            result = generator.cache.lookup(
                hashes.deck_hash,
                hashes.canonical_schedule_hash,
                hashes.summary_hash,
            )
            if result is None:
                raise RuntimeError(
                    f"{source}:{scenario_id}: OPM cache miss; Flow запускать запрещено"
                )
            if result.status is not RunStatus.OK:
                raise RuntimeError(
                    f"{source}:{scenario_id}: cached run имеет статус {result.status}"
                )
            response = loader.load(
                result,
                deck.summary_plan,
                material.schedule,
                densities,
            )
            metadata = RunMetadata(
                scenario_id=scenario_id,
                family=material.spec.family,
                seed=material.spec.seed,
                spec_hash=material.spec.spec_hash,
                canonical_schedule_hash=result.canonical_schedule_hash,
                deck_hash=result.deck_hash,
                summary_hash=result.summary_hash,
                run_id=result.run_id,
                status=result.status,
                unreachable_setpoint_fraction=material.unreachable_fraction,
                wallclock_seconds=result.wallclock_seconds,
                from_cache=True,
                response_hash=response.response_hash,
            )
            samples.append(
                DatasetSample(
                    schedule=material.schedule,
                    response=response,
                    metadata=metadata,
                )
            )
            shutil.rmtree(deck.data_file.parent)
            if index == 1 or index % 10 == 0 or index == len(identities):
                _log(f"cache {index}/{len(identities)}")
    return tuple(samples)


def _score_diagnostics(actual: list[float], predicted: list[float]) -> dict:
    actual_mean = statistics.mean(actual)
    predicted_mean = statistics.mean(predicted)
    actual_variance = math.fsum((value - actual_mean) ** 2 for value in actual)
    slope = math.fsum(
        (fact - actual_mean) * (estimate - predicted_mean)
        for fact, estimate in zip(actual, predicted)
    ) / actual_variance
    actual_order = sorted(range(len(actual)), key=lambda i: (-actual[i], i))
    predicted_order = sorted(range(len(predicted)), key=lambda i: (-predicted[i], i))
    residual = [estimate - fact for fact, estimate in zip(actual, predicted)]
    return {
        "ranking_extended": asdict(
            ranking_metrics(
                actual,
                predicted,
                k_values=(1, 3, 5, 10, 20, 26, 40),
            )
        ),
        "rank_of_true_best": predicted_order.index(actual_order[0]) + 1,
        "slope_predicted_on_actual": slope,
        "sd_ratio": statistics.pstdev(predicted) / statistics.pstdev(actual),
        "bias_rub": predicted_mean - actual_mean,
        "raw_mae_rub": statistics.mean(abs(value) for value in residual),
        "centered_residual_sd_rub": statistics.pstdev(residual),
    }


def _load_report(path: Path) -> dict:
    if not path.exists():
        return {
            "format": "aios.surrogate-bundle-evaluation.v1",
            "models": {},
            "calibrations": {},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != "aios.surrogate-bundle-evaluation.v1":
        raise RuntimeError(f"неподдержанный evaluation report: {payload.get('format')}")
    return payload


def _save_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    split_payload = json.loads(args.split_report.read_text(encoding="utf-8"))
    identities = split_payload["split_identity"]
    context = ModelZFeatureArtifact.load(args.feature_context)
    if context.n_training_scenarios < 400:
        raise RuntimeError("evaluation запрещён на пилотном feature context")
    normatives = load_normatives(args.normatives)
    materials = _materials(args.model_dir, args.data_root)
    checkpoints = {
        "rank": args.rank_checkpoint,
        "physical": args.physical_checkpoint,
        "published": args.published_checkpoint,
    }
    models = {name: TrajectorySurrogate.load(path) for name, path in checkpoints.items()}
    report = _load_report(args.output)
    report.update(
        {
            "feature_context": str(args.feature_context),
            "feature_context_training_scenarios": context.n_training_scenarios,
            "dataset_hash": context.dataset_hash,
            "split_report": str(args.split_report),
            "split_identity": identities,
            "checkpoints": {
                name: {"path": str(path), "model_version": models[name].version}
                for name, path in checkpoints.items()
            },
        }
    )

    for bucket in ("validation", "test"):
        pending = [
            name
            for name in models
            if bucket not in report["models"].get(name, {})
        ]
        if not pending:
            _log(f"{bucket}: все модели уже оценены")
            continue
        _log(f"{bucket}: загрузка {len(identities[bucket])} cached OPM responses")
        samples = _load_cached_samples(
            identities[bucket],
            materials=materials,
            model_dir=args.model_dir,
            data_root=args.data_root,
        )
        examples = _examples(samples, context)
        _log(f"{bucket}: признаки готовы")
        reference_actual = None
        for name in pending:
            _log(f"{bucket}: оценка {name}")
            metrics = evaluate(
                models[name],
                examples,
                samples,
                context,
                model_schedule_path=args.model_dir / "Model_Z_sch.inc",
                normatives=normatives,
                oil_density_t_per_m3=args.oil_density,
            )
            actual = metrics["actual_npv_rub"]
            predicted = metrics["predicted_npv_rub"]
            if reference_actual is None:
                reference_actual = actual
            elif actual != reference_actual:
                raise RuntimeError("фактический ЧДД различается между моделями")
            metrics["score_diagnostics"] = _score_diagnostics(actual, predicted)
            report["models"].setdefault(name, {})[bucket] = metrics
            if bucket == "validation":
                calibration = fit_npv_calibration(
                    actual,
                    predicted,
                    model_version=models[name].version,
                )
                report["calibrations"][name] = asdict(calibration)
                if name in {"rank", "physical"}:
                    calibration.save(checkpoints[name].parent / "npv_calibration.json")
            else:
                calibration = NpvCalibration(**report["calibrations"][name])
            metrics["validation_affine_calibration"] = calibration_metrics(
                actual,
                predicted,
                calibration,
            )
            _save_report(args.output, report)
            ranking = metrics["score_diagnostics"]["ranking_extended"]
            _log(
                f"{bucket}:{name}: rho={ranking['spearman_rank_correlation']:.4f}; "
                f"champion={metrics['score_diagnostics']['rank_of_true_best']}; "
                f"target_oil={metrics['target_mae']['oil_mass_delta']:.4f}"
            )
        del examples, samples
        gc.collect()

    _save_report(args.output, report)
    _log(f"готово: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
