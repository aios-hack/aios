"""Evaluate one trajectory ensemble on cached validation responses only."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import torch
if __package__:
    from tools.surrogate_evaluate_bundle import _score_diagnostics
    from tools.surrogate_select_physical_ensemble import _predict
else:
    from surrogate_evaluate_bundle import _score_diagnostics
    from surrogate_select_physical_ensemble import _predict

from bridge.dataset import DatasetSample, RunMetadata, dataset_base_schedule
from bridge.dataset_plan import build_plan, materialize
from bridge.opm_deck import OpmDeckEmitter
from bridge.response_loader import ResponseLoader, load_density_by_pvtnum
from bridge.summary import build_summary_plan
from config.schema import default_policies
from contracts import RunResult, RunStatus, hash_schedule
from economics import load_normatives
from economics import analyze_base_case
from schedule import parse_schedule
from surrogate.cycle import EXTRA_CONFIG, PILOT_CONFIG
from surrogate.adapter import ResponseAdapter
from surrogate.ensemble import TrajectoryEnsemble
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.raw_model_output import RawModelOutput, RawWellStepPrediction
from surrogate.train import _evaluation_artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--split-report", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--ensemble", type=Path, required=True)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oil-density", type=float, default=0.9131)
    parser.add_argument("--device", default="cpu")
    return parser


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _cache_index(root: Path) -> dict[str, RunResult]:
    result = {}
    for path in (root / "cache").glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            run = RunResult(
                run_id=row["run_id"],
                status=RunStatus(row["status"]),
                deck_hash=row["deck_hash"],
                canonical_schedule_hash=row["canonical_schedule_hash"],
                summary_hash=row["summary_hash"],
                artifacts=tuple(row["artifacts"]),
                wallclock_seconds=row["wallclock_seconds"],
                message=row["message"],
            )
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            continue
        if run.status is RunStatus.OK and all(
            Path(item).is_file() for item in run.artifacts
        ):
            result[run.canonical_schedule_hash] = run
    return result


def _load_validation_samples_fast(
    identities: list[dict[str, str]],
    *,
    model_dir: Path,
    data_root: Path,
) -> tuple[DatasetSample, ...]:
    emitter = OpmDeckEmitter(model_dir)
    base = dataset_base_schedule(model_dir, emitter)
    summary_plan = build_summary_plan(model_dir, emitter.source_wells)
    densities = load_density_by_pvtnum(model_dir)
    loader = ResponseLoader()
    by_source: dict[str, dict[str, object]] = {}
    for source, seed, config in (
        ("dataset-main", 20260816, PILOT_CONFIG),
        ("dataset-extra-500", 20260817, EXTRA_CONFIG),
    ):
        plan = build_plan(base, seed=seed, config=config)
        by_source[source] = {
            "specs": {item.scenario_id: item for item in plan.specs},
            "cache": _cache_index(data_root / source),
        }

    samples = []
    for index, identity in enumerate(identities, start=1):
        source = identity["source_dataset"]
        source_data = by_source[source]
        spec = source_data["specs"][identity["scenario_id"]]  # type: ignore[index]
        material = materialize(base, spec)  # type: ignore[arg-type]
        actual_hash = hash_schedule(material.schedule)
        expected_hash = identity["canonical_schedule_hash"]
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"{source}:{identity['scenario_id']}: schedule hash differs"
            )
        run = source_data["cache"].get(expected_hash)  # type: ignore[union-attr]
        if run is None:
            raise RuntimeError(
                f"{source}:{identity['scenario_id']}: cached OPM response missing"
            )
        response = loader.load(
            run, summary_plan, material.schedule, densities  # type: ignore[arg-type]
        )
        samples.append(
            DatasetSample(
                schedule=material.schedule,
                response=response,
                metadata=RunMetadata(
                    scenario_id=identity["scenario_id"],
                    family=spec.family,  # type: ignore[union-attr]
                    seed=spec.seed,  # type: ignore[union-attr]
                    spec_hash=spec.spec_hash,  # type: ignore[union-attr]
                    canonical_schedule_hash=(
                        run.canonical_schedule_hash  # type: ignore[union-attr]
                    ),
                    deck_hash=run.deck_hash,  # type: ignore[union-attr]
                    summary_hash=run.summary_hash,  # type: ignore[union-attr]
                    run_id=run.run_id,  # type: ignore[union-attr]
                    status=run.status,  # type: ignore[union-attr]
                    unreachable_setpoint_fraction=material.unreachable_fraction,
                    wallclock_seconds=run.wallclock_seconds,  # type: ignore[union-attr]
                    from_cache=True,
                    response_hash=response.response_hash,
                ),
            )
        )
        if index == 1 or index % 10 == 0 or index == len(identities):
            print(f"direct cache {index}/{len(identities)}", flush=True)
    return tuple(samples)


def main() -> int:
    args = _parser().parse_args()
    started = time.monotonic()
    split = json.loads(args.split_report.read_text(encoding="utf-8"))
    identities = split["split_identity"]["validation"]
    if len(identities) != 105:
        raise RuntimeError(f"expected 105 validation identities, got {len(identities)}")
    context = ModelZFeatureArtifact.load(args.feature_context)
    ensemble = TrajectoryEnsemble.load(args.ensemble)
    if ensemble.dataset_hash != context.dataset_hash:
        raise RuntimeError("ensemble/context dataset hashes differ")
    blob = torch.load(args.tensors, map_location="cpu", weights_only=False, mmap=True)
    if blob.get("dataset_hash") != context.dataset_hash:
        raise RuntimeError("tensor/context dataset hashes differ")
    if blob["identities"]["validation"] != identities:
        raise RuntimeError("tensor/split validation identities differ")
    x, well_index, _ = blob["tensors"]["validation"]
    member_predictions = []
    for index, model in enumerate(ensemble.models, start=1):
        print(f"batched member {index}/{len(ensemble.models)}", flush=True)
        member_predictions.append(_predict(model, x, well_index, args.device))
    predicted = sum(
        weight * values
        for weight, values in zip(ensemble.weights, member_predictions)
    )
    del member_predictions
    samples = _load_validation_samples_fast(
        identities,
        model_dir=args.model_dir,
        data_root=args.data_root,
    )

    parsed = parse_schedule((args.model_dir / "Model_Z_sch.inc").read_bytes())
    normatives = load_normatives(args.normatives)
    policies = default_policies()
    adapter = ResponseAdapter()
    actual_npv = []
    predicted_npv = []
    offset = 0
    wells = tuple(blob["wells"])
    for index, (sample, count) in enumerate(
        zip(samples, blob["counts"]["validation"], strict=True), start=1
    ):
        if sample.response is None:
            raise RuntimeError("validation sample has no response")
        stop = offset + count
        source = x[offset:stop]
        indices = well_index[offset:stop]
        values = predicted[offset:stop]
        steps = torch.round(source[:, 11] * 223).to(torch.long)
        nodes = tuple(
            RawWellStepPrediction(
                well=wells[int(well)],
                control_step=int(step),
                oil_mass_delta=float(row[0]),
                liquid_volume_delta=float(row[1]),
                injection_volume_delta=float(row[2]),
                liquid_rate=float(row[3]),
                injection_rate=float(row[4]),
                bhp=float(row[5]),
            )
            for well, step, row in zip(indices, steps, values, strict=True)
        )
        raw = RawModelOutput(
            canonical_schedule_hash=sample.metadata.canonical_schedule_hash,
            wells=wells,
            nodes=nodes,
        )
        states, intervals = adapter.adapt(
            raw,
            sample.schedule,
            sample.response,
            context.context.control_dates,
        )
        artifact = _evaluation_artifact(
            ensemble.version, sample, states, intervals
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
                artifact,
                parsed.dates,
                parsed.t0_deck_date_index,
                normatives,
                policies,
            ).npv_methodology
        )
        offset = stop
        if index == 1 or index % 10 == 0 or index == len(samples):
            print(f"economics {index}/{len(samples)}", flush=True)
    if offset != len(predicted) or not all(map(math.isfinite, predicted_npv)):
        raise RuntimeError("batched prediction was not consumed exactly")
    metrics = {
        "actual_npv_rub": actual_npv,
        "predicted_npv_rub": predicted_npv,
    }
    metrics["score_diagnostics"] = _score_diagnostics(
        metrics["actual_npv_rub"], metrics["predicted_npv_rub"]
    )
    report = {
        "format": "aios.trajectory-ensemble-npv-validation.v1",
        "selection_bucket": "validation",
        "locked_test_read": False,
        "dataset_hash": context.dataset_hash,
        "ensemble_version": ensemble.version,
        "split_report": str(args.split_report),
        "identities": identities,
        "metrics": metrics,
        "seconds": time.monotonic() - started,
    }
    _write_json(args.output, report)
    ranking = metrics["score_diagnostics"]["ranking_extended"]
    print(
        f"validation rho={ranking['spearman_rank_correlation']:.4f}; "
        f"MAE={metrics['score_diagnostics']['raw_mae_rub'] / 1e6:.2f}m",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
