"""Predict blind-plan NPV with the frozen physical ensemble, response-free."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import replace
from pathlib import Path

import torch

if __package__:
    from tools.surrogate_evaluate_blind_npv import _plan_from_artifact
    from tools.surrogate_freeze_blind_protocol import _assert_response_free
    from tools.surrogate_select_physical_ensemble import _predict
else:
    from surrogate_evaluate_blind_npv import _plan_from_artifact
    from surrogate_freeze_blind_protocol import _assert_response_free
    from surrogate_select_physical_ensemble import _predict

from bridge.dataset_plan import materialize
from config.schema import default_policies
from contracts import ResponseArtifact, canonical_bytes, hash_schedule
from economics import analyze_base_case, load_normatives, load_response_artifact
from schedule import parse_schedule
from surrogate.adapter import ResponseAdapter
from surrogate.ensemble import TrajectoryEnsemble
from surrogate.features import ScheduleFeatureizer
from surrogate.model import _features
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.ood import score
from surrogate.raw_model_output import RawModelOutput, RawWellStepPrediction


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--ensemble", type=Path, required=True)
    parser.add_argument("--locked-predictions", type=Path)
    parser.add_argument("--require-response-free-plan", action="store_true")
    parser.add_argument("--base-response", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _prediction_artifact(
    ensemble_version: str,
    scenario_id: str,
    schedule_hash: str,
    states: tuple,
    intervals: tuple,
) -> ResponseArtifact:
    identity = {
        "ensemble_version": ensemble_version,
        "scenario_id": scenario_id,
        "schedule_hash": schedule_hash,
    }
    return ResponseArtifact(
        source_run_id=f"surrogate-blind-physical:{ensemble_version[:12]}",
        response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
        state_at_date=states,
        interval_response=intervals,
    )


def main() -> int:
    args = _parser().parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite physical cache: {args.output}")
    started = time.monotonic()
    if args.locked_predictions is None and not args.require_response_free_plan:
        raise RuntimeError(
            "physical prediction without a lock requires a response-free plan"
        )
    if args.require_response_free_plan:
        _assert_response_free(args.dataset_root)
    input_sha256 = {
        "feature_context": _sha256(args.feature_context),
        "ensemble": _sha256(args.ensemble),
        "base_response": _sha256(args.base_response),
        "normatives": _sha256(args.normatives),
    }
    if args.locked_predictions is not None:
        input_sha256["locked_predictions"] = _sha256(args.locked_predictions)
        locked = json.loads(args.locked_predictions.read_text(encoding="utf-8"))
        if (
            locked.get("response_data_read") is not False
            or locked.get("historical_test_read") is not False
        ):
            raise RuntimeError("locked prediction provenance is unsafe")
    else:
        locked = None
    _, base, plan = _plan_from_artifact(args.model_dir, args.dataset_root)
    if locked is not None and locked.get("plan_hash") != plan.plan_hash:
        raise RuntimeError("locked prediction/plan hashes differ")
    locked_by_id = (
        {row["scenario_id"]: row for row in locked["rows"]}
        if locked is not None
        else {}
    )
    if locked is not None and len(locked_by_id) != len(plan.specs):
        raise RuntimeError("locked predictions do not uniquely cover plan")

    context = ModelZFeatureArtifact.load(args.feature_context)
    ensemble = TrajectoryEnsemble.load(args.ensemble)
    if context.dataset_hash != ensemble.dataset_hash:
        raise RuntimeError("ensemble/context dataset hashes differ")
    history = load_response_artifact(args.base_response)
    normatives = load_normatives(args.normatives)
    parsed = parse_schedule((args.model_dir / "Model_Z_sch.inc").read_bytes())
    policies = default_policies()
    featureizer = ScheduleFeatureizer()
    adapter = ResponseAdapter()

    prepared = []
    node_features = []
    well_indices = []
    for index, spec in enumerate(
        sorted(plan.specs, key=lambda item: item.scenario_id), start=1
    ):
        material = materialize(base, spec)
        schedule_hash = hash_schedule(material.schedule)
        locked_row = locked_by_id.get(spec.scenario_id)
        if (
            locked_row is not None
            and locked_row["canonical_schedule_hash"] != schedule_hash
        ):
            raise RuntimeError(f"{spec.scenario_id}: schedule hash differs")
        candidate = replace(
            featureizer.transform(material.schedule, context.context),
            lambda_edges=(),
        )
        x, well_index = _features(
            candidate,
            ensemble.wells,
            scenario_context=True,
        )
        prepared.append((spec, material, schedule_hash, locked_row, candidate))
        node_features.append(x)
        well_indices.append(well_index)
        if index == 1 or index % 10 == 0 or index == len(plan.specs):
            print(f"physical input {index}/{len(plan.specs)}", flush=True)

    x = torch.cat(node_features)
    well_index = torch.cat(well_indices)
    member_predictions = []
    for index, model in enumerate(ensemble.models, start=1):
        print(f"physical member {index}/{len(ensemble.models)}", flush=True)
        member_predictions.append(_predict(model, x, well_index, "cpu"))
    predicted_nodes = sum(
        weight * values
        for weight, values in zip(ensemble.weights, member_predictions, strict=True)
    )
    del member_predictions

    rows = []
    offset = 0
    fields = (
        "oil_mass_delta",
        "liquid_volume_delta",
        "injection_volume_delta",
        "liquid_rate",
        "injection_rate",
        "bhp",
    )
    for index, (spec, material, schedule_hash, locked_row, candidate) in enumerate(
        prepared, start=1
    ):
        stop = offset + len(candidate.nodes)
        values = predicted_nodes[offset:stop]
        raw = RawModelOutput(
            canonical_schedule_hash=schedule_hash,
            wells=candidate.wells,
            nodes=tuple(
                RawWellStepPrediction(
                    well=node.well,
                    control_step=node.control_step,
                    **{
                        field: float(value)
                        for field, value in zip(fields, row, strict=True)
                    },
                )
                for node, row in zip(candidate.nodes, values, strict=True)
            ),
        )
        assessment = score(candidate, ensemble.models[0].domain)
        states, intervals = adapter.adapt(
            raw,
            material.schedule,
            history,
            context.context.control_dates,
        )
        predicted = _prediction_artifact(
            ensemble.version,
            spec.scenario_id,
            schedule_hash,
            states,
            intervals,
        )
        npv_rub = analyze_base_case(
            predicted,
            parsed.dates,
            parsed.t0_deck_date_index,
            normatives,
            policies,
        ).npv_methodology
        if not math.isfinite(npv_rub):
            raise RuntimeError(f"{spec.scenario_id}: non-finite physical NPV")
        row = {
                "scenario_id": spec.scenario_id,
                "family": spec.family.value,
                "canonical_schedule_hash": schedule_hash,
                "physical_npv_rub": npv_rub,
                "ood_score": (
                    assessment.score if math.isfinite(assessment.score) else None
                ),
                "ood_score_infinite": math.isinf(assessment.score),
                "n_ood_exceedances": len(assessment.exceedances),
            }
        if locked_row is not None:
            row.update(
                {
                    "baseline_npv_rub": locked_row["v2_npv_rub"],
                    "candidate_npv_rub": locked_row["v3_npv_rub"],
                }
            )
        rows.append(row)
        offset = stop
        if index == 1 or index % 10 == 0 or index == len(plan.specs):
            print(f"physical blind NPV {index}/{len(plan.specs)}", flush=True)
    if offset != len(predicted_nodes):
        raise RuntimeError("batched physical predictions were not consumed exactly")

    final_sha256 = {
        "feature_context": _sha256(args.feature_context),
        "ensemble": _sha256(args.ensemble),
        "base_response": _sha256(args.base_response),
        "normatives": _sha256(args.normatives),
    }
    if args.locked_predictions is not None:
        final_sha256["locked_predictions"] = _sha256(args.locked_predictions)
    if final_sha256 != input_sha256:
        raise RuntimeError("physical prediction inputs changed during cache build")
    report = {
        "format": "aios.surrogate-blind-physical-npv.v1",
        "response_data_read": False,
        "base_historical_response_read": True,
        "historical_test_read": False,
        "frozen_before_blind_responses": args.require_response_free_plan,
        "selection_eligible_after_blind_disclosure_only": True,
        "plan_hash": plan.plan_hash,
        "dataset_hash": ensemble.dataset_hash,
        "ensemble_version": ensemble.version,
        "n_scenarios": len(rows),
        "input_sha256": input_sha256,
        "rows": rows,
        "seconds": time.monotonic() - started,
    }
    _write_json(args.output, report)
    print(f"physical blind NPV written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
