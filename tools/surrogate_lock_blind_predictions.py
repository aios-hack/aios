"""Freeze v2/v3 predictions for a blind plan before reading any response."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

if __package__:
    from tools.surrogate_evaluate_blind_npv import (
        _plan_from_artifact,
        _sha256,
        _validate_protocol,
    )
else:
    from surrogate_evaluate_blind_npv import (
        _plan_from_artifact,
        _sha256,
        _validate_protocol,
    )

from bridge.dataset_plan import materialize
from contracts import hash_schedule
from surrogate.features import ScheduleFeatureizer
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.npv_block_head import (
    load_direct_npv_head,
    validate_direct_npv_head_context,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--baseline-head", type=Path, required=True)
    parser.add_argument("--candidate-head", type=Path, required=True)
    parser.add_argument("--candidate-physical-npv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _write_json(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(
            f"refusing to overwrite locked prediction artifact: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    if args.output.exists():
        raise FileExistsError(
            f"refusing to overwrite locked prediction artifact: {args.output}"
        )
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    _, base, plan = _plan_from_artifact(args.model_dir, args.dataset_root)
    v2 = load_direct_npv_head(args.baseline_head)
    v3 = load_direct_npv_head(args.candidate_head)
    _validate_protocol(
        protocol,
        baseline_path=args.baseline_head,
        baseline=v2,
        candidate_path=args.candidate_head,
        candidate=v3,
        blind={"plan_hash": plan.plan_hash, "n_scenarios": len(plan.specs)},
        bootstrap_replicates=protocol["bootstrap"]["replicates"],
    )
    baseline_physical_weight = float(
        getattr(v2, "physical_npv_weight", 0.0)
    )
    candidate_physical_weight = float(
        getattr(v3, "physical_npv_weight", 0.0)
    )
    if baseline_physical_weight > 0.0 and (
        getattr(v2, "physical_ensemble_version", "")
        != getattr(v3, "physical_ensemble_version", "")
    ):
        raise RuntimeError(
            "blended baseline and candidate require the same physical ensemble"
        )
    if baseline_physical_weight > 0.0 or candidate_physical_weight > 0.0:
        if args.candidate_physical_npv is None:
            raise RuntimeError("physical blend requires locked physical NPV")
        physical = json.loads(
            args.candidate_physical_npv.read_text(encoding="utf-8")
        )
        expected_physical_sha = protocol["candidate"].get(
            "physical_npv_predictions_sha256"
        )
        physical_rows = physical.get("rows")
        if (
            _sha256(args.candidate_physical_npv) != expected_physical_sha
            or physical.get("format") != "aios.surrogate-blind-physical-npv.v1"
            or physical.get("response_data_read") is not False
            or physical.get("historical_test_read") is not False
            or physical.get("frozen_before_blind_responses") is not True
            or physical.get("plan_hash") != plan.plan_hash
            or physical.get("ensemble_version")
            != getattr(
                v3 if candidate_physical_weight > 0.0 else v2,
                "physical_ensemble_version",
                "",
            )
            or not isinstance(physical_rows, list)
            or len(physical_rows) != len(plan.specs)
        ):
            raise RuntimeError("locked physical NPV differs from protocol")
        physical_by_id = {row["scenario_id"]: row for row in physical_rows}
        if len(physical_by_id) != len(plan.specs):
            raise RuntimeError("locked physical NPV does not uniquely cover plan")
    elif args.candidate_physical_npv is not None:
        raise RuntimeError("non-blended candidate must not receive physical NPV")
    else:
        physical_by_id = {}
    context = ModelZFeatureArtifact.load(args.feature_context)
    context_sha256 = _sha256(args.feature_context)
    if protocol.get("feature_context_sha256") not in {None, context_sha256}:
        raise RuntimeError("protocol feature context bytes differ")
    for head in (v2, v3):
        validate_direct_npv_head_context(
            head,
            context_dataset_hash=context.dataset_hash,
            feature_context_sha256=context_sha256,
        )
    if v2.wells != v3.wells or v2.static_feature_names != v3.static_feature_names:
        raise RuntimeError("baseline/candidate feature axes differ")
    featureizer = ScheduleFeatureizer()
    rows = []
    for index, spec in enumerate(
        sorted(plan.specs, key=lambda item: item.scenario_id), start=1
    ):
        material = materialize(base, spec)
        candidate = replace(
            featureizer.transform(material.schedule, context.context),
            lambda_edges=(),
        )
        direct_candidate_npv = v3.predict(candidate)
        direct_baseline_npv = v2.predict(candidate)
        candidate_npv = direct_candidate_npv
        baseline_npv = direct_baseline_npv
        physical_npv = None
        if baseline_physical_weight > 0.0 or candidate_physical_weight > 0.0:
            physical_row = physical_by_id[spec.scenario_id]
            if physical_row["canonical_schedule_hash"] != hash_schedule(
                material.schedule
            ):
                raise RuntimeError(f"{spec.scenario_id}: physical schedule differs")
            physical_npv = physical_row["physical_npv_rub"]
        if baseline_physical_weight > 0.0:
            baseline_npv = (
                (1.0 - baseline_physical_weight) * direct_baseline_npv
                + baseline_physical_weight * physical_npv
            )
        if candidate_physical_weight > 0.0:
            candidate_npv = (
                (1.0 - candidate_physical_weight) * direct_candidate_npv
                + candidate_physical_weight * physical_npv
            )
        row = {
            "scenario_id": spec.scenario_id,
            "family": spec.family.value,
            "canonical_schedule_hash": hash_schedule(material.schedule),
            "v2_npv_rub": baseline_npv,
            "v2_direct_npv_rub": direct_baseline_npv,
            "v3_npv_rub": candidate_npv,
            "v3_direct_npv_rub": direct_candidate_npv,
        }
        if physical_npv is not None:
            row["physical_npv_rub"] = physical_npv
        rows.append(row)
        if index == 1 or index % 10 == 0 or index == len(plan.specs):
            print(f"lock predictions {index}/{len(plan.specs)}", flush=True)
    payload = {
        "format": "aios.surrogate-locked-blind-predictions.v1",
        "response_data_read": False,
        "historical_test_read": False,
        "plan_hash": plan.plan_hash,
        "protocol": str(args.protocol),
        "protocol_sha256": _sha256(args.protocol),
        "baseline_version": v2.version,
        "candidate_version": v3.version,
        "baseline_target_provenance_hash": v2.target_provenance_hash,
        "candidate_target_provenance_hash": v3.target_provenance_hash,
        "baseline_feature_context_sha256": v2.feature_context_sha256,
        "candidate_feature_context_sha256": v3.feature_context_sha256,
        "n_scenarios": len(rows),
        "rows": rows,
    }
    if args.candidate_physical_npv is not None:
        physical_sha256 = _sha256(args.candidate_physical_npv)
        payload["candidate_physical_npv_sha256"] = physical_sha256
        payload["candidate_physical_npv_weight"] = candidate_physical_weight
        if baseline_physical_weight > 0.0:
            payload["baseline_physical_npv_sha256"] = physical_sha256
            payload["baseline_physical_npv_weight"] = baseline_physical_weight
    _write_json(args.output, payload)
    print(f"locked predictions: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
