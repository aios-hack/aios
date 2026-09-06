"""Cache response-free full NPV feature vectors for a locked blind plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import torch

if __package__:
    from tools.surrogate_evaluate_blind_npv import _plan_from_artifact
else:
    from surrogate_evaluate_blind_npv import _plan_from_artifact

from bridge.dataset_plan import materialize
from contracts import hash_schedule
from surrogate.features import ScheduleFeatureizer
from surrogate.model import _features
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.npv_block_head import (
    direct_npv_feature_set,
    load_direct_npv_head,
    validate_direct_npv_head_context,
)
from surrogate.npv_head import (
    feature_implementation_hash,
    scenario_feature_vector,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--locked-predictions", type=Path, required=True)
    parser.add_argument("--baseline-head", type=Path, required=True)
    parser.add_argument("--candidate-head", type=Path, required=True)
    parser.add_argument(
        "--feature-set", choices=("full", "economic"), default="full"
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locked_direct_candidate_npv(
    row: dict[str, object], *, physical_npv_weight: float
) -> object:
    if physical_npv_weight > 0.0:
        if "v3_direct_npv_rub" not in row:
            raise RuntimeError(
                "locked physical blend lacks its frozen direct prediction"
            )
        return row["v3_direct_npv_rub"]
    return row.get("v3_npv_rub")


def main() -> int:
    args = _parser().parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite blind feature cache: {args.output}")
    input_sha256 = {
        "locked_predictions": _sha256(args.locked_predictions),
        "baseline_head": _sha256(args.baseline_head),
        "candidate_head": _sha256(args.candidate_head),
        "feature_context": _sha256(args.feature_context),
        "feature_implementation": feature_implementation_hash(),
    }
    locked = json.loads(args.locked_predictions.read_text(encoding="utf-8"))
    if (
        locked.get("response_data_read") is not False
        or locked.get("historical_test_read") is not False
    ):
        raise RuntimeError("locked prediction provenance is unsafe")
    _, base, plan = _plan_from_artifact(args.model_dir, args.dataset_root)
    if locked.get("plan_hash") != plan.plan_hash:
        raise RuntimeError("locked prediction/plan hashes differ")
    context = ModelZFeatureArtifact.load(args.feature_context)
    v2 = load_direct_npv_head(args.baseline_head)
    v3 = load_direct_npv_head(args.candidate_head)
    context_sha256 = _sha256(args.feature_context)
    for head in (v2, v3):
        validate_direct_npv_head_context(
            head,
            context_dataset_hash=context.dataset_hash,
            feature_context_sha256=context_sha256,
        )
    if v2.wells != v3.wells or v2.static_feature_names != v3.static_feature_names:
        raise RuntimeError("baseline/candidate feature axes differ")
    locked_by_id = {row["scenario_id"]: row for row in locked["rows"]}
    if len(locked_by_id) != len(plan.specs):
        raise RuntimeError("locked predictions do not uniquely cover plan")
    featureizer = ScheduleFeatureizer()
    vectors = []
    identities = []
    for index, spec in enumerate(
        sorted(plan.specs, key=lambda item: item.scenario_id), start=1
    ):
        material = materialize(base, spec)
        schedule_hash = hash_schedule(material.schedule)
        locked_row = locked_by_id[spec.scenario_id]
        if locked_row["canonical_schedule_hash"] != schedule_hash:
            raise RuntimeError(f"{spec.scenario_id}: schedule hash differs")
        candidate = replace(
            featureizer.transform(material.schedule, context.context),
            lambda_edges=(),
        )
        x, well_index = _features(candidate, v2.wells, scenario_context=False)
        prediction_vectors = {
            feature_set: scenario_feature_vector(
                x,
                well_index,
                n_wells=len(v2.wells),
                feature_set=feature_set,
            )
            for feature_set in {
                direct_npv_feature_set(v2),
                direct_npv_feature_set(v3),
                args.feature_set,
            }
        }
        if (
            v2.predict_vector(prediction_vectors[direct_npv_feature_set(v2)])
            != locked_row["v2_npv_rub"]
            or v3.predict_vector(prediction_vectors[direct_npv_feature_set(v3)])
            != _locked_direct_candidate_npv(
                locked_row,
                physical_npv_weight=float(v3.physical_npv_weight),
            )
        ):
            raise RuntimeError(f"{spec.scenario_id}: vector prediction differs")
        vector = prediction_vectors[args.feature_set]
        vectors.append(vector.to(torch.float32))
        identities.append(
            {
                "scenario_id": spec.scenario_id,
                "family": spec.family.value,
                "canonical_schedule_hash": schedule_hash,
            }
        )
        if index == 1 or index % 10 == 0 or index == len(plan.specs):
            print(f"blind feature cache {index}/{len(plan.specs)}", flush=True)
    matrix = torch.stack(vectors)
    expected_width = 2908 if args.feature_set == "full" else 4406
    if matrix.shape != (len(plan.specs), expected_width) or not bool(
        torch.isfinite(matrix).all()
    ):
        raise RuntimeError("blind feature matrix is incomplete or non-finite")
    final_sha256 = {
        "locked_predictions": _sha256(args.locked_predictions),
        "baseline_head": _sha256(args.baseline_head),
        "candidate_head": _sha256(args.candidate_head),
        "feature_context": _sha256(args.feature_context),
        "feature_implementation": feature_implementation_hash(),
    }
    if final_sha256 != input_sha256:
        raise RuntimeError("blind feature inputs changed during cache build")
    payload = {
        "format": (
            "aios.surrogate-blind-npv-features.v1"
            if args.feature_set == "full"
            else "aios.surrogate-blind-npv-features.v2"
        ),
        "response_data_read": False,
        "historical_test_read": False,
        "plan_hash": plan.plan_hash,
        "dataset_hash": context.dataset_hash,
        "feature_set": args.feature_set,
        "feature_width": matrix.shape[1],
        "feature_provenance_hash": input_sha256["feature_implementation"],
        "feature_context_sha256": context_sha256,
        "locked_predictions_sha256": input_sha256["locked_predictions"],
        "baseline_head_sha256": input_sha256["baseline_head"],
        "candidate_head_sha256": input_sha256["candidate_head"],
        "baseline_version": v2.version,
        "candidate_version": v3.version,
        "identities": identities,
        "features": matrix,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(args.output)
    print(f"blind feature cache written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
