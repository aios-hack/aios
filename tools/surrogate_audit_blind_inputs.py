"""Audit blind schedules against the production input OOD domain response-free."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

if __package__:
    from tools.surrogate_evaluate_blind_npv import _plan_from_artifact
else:
    from surrogate_evaluate_blind_npv import _plan_from_artifact

from bridge.dataset_plan import materialize
from contracts import hash_schedule
from surrogate.ensemble import TrajectoryEnsemble
from surrogate.features import ScheduleFeatureizer
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.ood import score
from surrogate.per_well_ood import PerWellInputDomain


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--ensemble", type=Path, required=True)
    parser.add_argument("--locked-predictions", type=Path, required=True)
    parser.add_argument("--per-well-domain", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    locked = json.loads(args.locked_predictions.read_text(encoding="utf-8"))
    _, base, plan = _plan_from_artifact(args.model_dir, args.dataset_root)
    if locked.get("plan_hash") != plan.plan_hash:
        raise RuntimeError("locked prediction/plan hashes differ")
    locked_by_id = {row["scenario_id"]: row for row in locked["rows"]}
    if len(locked_by_id) != len(plan.specs):
        raise RuntimeError("locked predictions do not uniquely cover the plan")
    context = ModelZFeatureArtifact.load(args.feature_context)
    ensemble = TrajectoryEnsemble.load(args.ensemble)
    if context.dataset_hash != ensemble.dataset_hash:
        raise RuntimeError("ensemble/context dataset hashes differ")
    domain = ensemble.models[0].domain
    per_well = (
        PerWellInputDomain.load(args.per_well_domain)
        if args.per_well_domain is not None
        else None
    )
    if per_well is not None and per_well.dataset_hash != ensemble.dataset_hash:
        raise RuntimeError("per-well/ensemble dataset hashes differ")
    featureizer = ScheduleFeatureizer()
    rows = []
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
        assessment = score(candidate, domain)
        finite_score = math.isfinite(assessment.score)
        per_well_assessment = per_well.score(candidate) if per_well else None
        per_well_score = per_well_assessment.score if per_well_assessment else 0.0
        finite_per_well_score = math.isfinite(per_well_score)
        rows.append(
            {
                "scenario_id": spec.scenario_id,
                "family": spec.family.value,
                "canonical_schedule_hash": schedule_hash,
                "ood_score": assessment.score if finite_score else None,
                "ood_score_infinite": math.isinf(assessment.score),
                "inside_strict_domain": assessment.score == 0.0,
                "n_exceedances": len(assessment.exceedances),
                "worst_feature": (
                    assessment.worst.feature if assessment.worst else None
                ),
                "worst_well": assessment.worst.well if assessment.worst else None,
                "worst_control_step": (
                    assessment.worst.control_step if assessment.worst else None
                ),
                "v2_npv_rub": locked_row["v2_npv_rub"],
                "v3_npv_rub": locked_row["v3_npv_rub"],
                "per_well_ood_score": (
                    per_well_score if finite_per_well_score else None
                ),
                "per_well_ood_infinite": math.isinf(per_well_score),
                "inside_per_well_domain": (
                    per_well_assessment is None
                    or per_well_score <= per_well.threshold
                ),
                "per_well_worst_feature": (
                    per_well_assessment.worst.feature
                    if per_well_assessment and per_well_assessment.worst
                    else None
                ),
            }
        )
        if index == 1 or index % 10 == 0 or index == len(plan.specs):
            print(f"blind OOD audit {index}/{len(plan.specs)}", flush=True)
    by_family = defaultdict(list)
    for row in rows:
        by_family[row["family"]].append(row)
    report = {
        "format": "aios.surrogate-blind-input-ood-audit.v1",
        "response_data_read": False,
        "historical_test_read": False,
        "plan_hash": plan.plan_hash,
        "ensemble_version": ensemble.version,
        "dataset_hash": ensemble.dataset_hash,
        "strict_threshold": 0.0,
        "per_well_domain_version": per_well.version if per_well else None,
        "per_well_threshold": per_well.threshold if per_well else None,
        "n_scenarios": len(rows),
        "n_inside": sum(row["inside_strict_domain"] for row in rows),
        "n_outside": sum(not row["inside_strict_domain"] for row in rows),
        "n_inside_per_well": sum(row["inside_per_well_domain"] for row in rows),
        "n_outside_per_well": sum(
            not row["inside_per_well_domain"] for row in rows
        ),
        "worst_feature_counts": dict(
            Counter(row["worst_feature"] for row in rows if row["worst_feature"])
        ),
        "by_family": {
            family: {
                "n": len(items),
                "inside": sum(item["inside_strict_domain"] for item in items),
                "outside": sum(not item["inside_strict_domain"] for item in items),
                "has_infinite_ood": any(
                    item["ood_score_infinite"] for item in items
                ),
                "max_finite_ood_score": max(
                    (
                        item["ood_score"]
                        for item in items
                        if item["ood_score"] is not None
                    ),
                    default=None,
                ),
                "inside_per_well": sum(
                    item["inside_per_well_domain"] for item in items
                ),
                "outside_per_well": sum(
                    not item["inside_per_well_domain"] for item in items
                ),
                "max_finite_per_well_ood_score": max(
                    (
                        item["per_well_ood_score"]
                        for item in items
                        if item["per_well_ood_score"] is not None
                    ),
                    default=None,
                ),
            }
            for family, items in sorted(by_family.items())
        },
        "rows": rows,
    }
    _write_json(args.output, report)
    print(
        f"global strict OOD: inside={report['n_inside']}; "
        f"outside={report['n_outside']}; per-well outside="
        f"{report['n_outside_per_well']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
