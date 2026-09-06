"""Atomically freeze a blind promotion protocol before any successful response."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

if __package__:
    from tools.surrogate_evaluate_blind_npv import (
        PRIMARY_BOOTSTRAP_SEED,
        PRECISION_AT_5_DIFFERENCE_MIN,
        SPEARMAN_CI_NONINFERIORITY,
        SPEARMAN_POINT_NONINFERIORITY,
        TRUE_BEST_RANK_MAX,
    )
else:
    from surrogate_evaluate_blind_npv import (
        PRIMARY_BOOTSTRAP_SEED,
        PRECISION_AT_5_DIFFERENCE_MIN,
        SPEARMAN_CI_NONINFERIORITY,
        SPEARMAN_POINT_NONINFERIORITY,
        TRUE_BEST_RANK_MAX,
    )

from surrogate.model_z_context import ModelZFeatureArtifact
from bridge.opm_deck import bundle_hash
from surrogate.npv_block_head import (
    load_direct_npv_head,
    validate_direct_npv_head_context,
)


PHYSICAL_PIPELINE_SOURCES = (
    "bridge/dataset.py",
    "bridge/dataset_plan.py",
    "bridge/opm_deck.py",
    "bridge/response_loader.py",
    "bridge/runner.py",
    "bridge/summary.py",
    "contracts/hashing.py",
    "contracts/response.py",
    "contracts/run_artifact.py",
    "contracts/schedule.py",
    "contracts/simulation.py",
    "schedule/build.py",
    "schedule/canonical.py",
    "schedule/lossless.py",
    "schedule/replay.py",
    "tools/surrogate_build_blind_dataset.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--opm-image", required=True)
    parser.add_argument("--baseline-head", type=Path, required=True)
    parser.add_argument("--candidate-head", type=Path, required=True)
    parser.add_argument("--candidate-physical-npv", type=Path)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--economics-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head_record(path: Path, head: object) -> dict[str, Any]:
    record = {
        "checkpoint_sha256": _sha256(path),
        "model_version": head.version,
    }
    for field in (
        "target_provenance_hash",
        "feature_provenance_hash",
        "feature_context_sha256",
        "physical_npv_weight",
        "physical_ensemble_version",
        "physical_blend_provenance_hash",
    ):
        value = getattr(head, field, "")
        if value:
            record[field] = value
    return record


def physical_pipeline_record(
    model_dir: Path, *, opm_image: str | None = None
) -> dict[str, Any]:
    """Hash code and exact Model_Z inputs used to create blind responses."""

    repository = Path(__file__).resolve().parents[1]
    source_paths = {name: repository / name for name in PHYSICAL_PIPELINE_SOURCES}
    missing = [name for name, path in source_paths.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"physical pipeline sources are missing: {missing}")
    resolved_model = model_dir.resolve()
    model_inputs = tuple(
        sorted(
            path
            for path in resolved_model.iterdir()
            if path.is_file() and path.suffix.lower() in {".data", ".inc"}
        )
    )
    if not model_inputs:
        raise RuntimeError("Model_Z physical input bundle is empty")
    record = {
        "format": "aios.surrogate-physical-pipeline-provenance.v1",
        "source_sha256": {
            name: _sha256(path) for name, path in source_paths.items()
        },
        "model_input_files": {
            path.name: _sha256(path) for path in model_inputs
        },
        "model_input_bundle_sha256": bundle_hash(model_inputs, resolved_model),
    }
    if opm_image is not None:
        if not (
            "@sha256:" in opm_image
            or re.fullmatch(r"sha256:[0-9a-f]{64}", opm_image)
        ):
            raise RuntimeError("blind2 OPM image must be pinned by immutable sha256 digest")
        record["opm_image"] = opm_image
    return record


def _assert_response_free(dataset_root: Path) -> None:
    cache = dataset_root / "cache"
    if cache.exists() and any(cache.glob("*.json")):
        raise RuntimeError("cannot freeze protocol after a successful blind response")
    manifest = dataset_root / "manifest.jsonl"
    if manifest.exists() and manifest.stat().st_size:
        raise RuntimeError("cannot freeze protocol after blind execution started")
    for name in ("report.json", "blind_report.json"):
        if (dataset_root / name).exists():
            raise RuntimeError("cannot freeze protocol after blind report exists")


def _write(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite frozen protocol: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    if args.bootstrap_replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    _assert_response_free(args.dataset_root)
    plan_path = args.dataset_root / "plan.json"
    exclusion_audit_path = args.dataset_root / "plan_exclusion_audit.json"
    input_sha256 = {
        "plan": _sha256(plan_path),
        "exclusion_audit": _sha256(exclusion_audit_path),
        "baseline_head": _sha256(args.baseline_head),
        "candidate_head": _sha256(args.candidate_head),
        "feature_context": _sha256(args.feature_context),
        "economics_lock": _sha256(args.economics_lock),
    }
    if args.candidate_physical_npv is not None:
        input_sha256["candidate_physical_npv"] = _sha256(
            args.candidate_physical_npv
        )
    physical_pipeline = physical_pipeline_record(
        args.model_dir, opm_image=args.opm_image
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    exclusion_audit = json.loads(
        exclusion_audit_path.read_text(encoding="utf-8")
    )
    scenarios = plan.get("scenarios")
    if (
        not isinstance(scenarios, list)
        or len(scenarios) != plan.get("n_scenarios")
        or len(scenarios) != 81
        or not isinstance(plan.get("seed"), int)
        or not isinstance(plan.get("plan_hash"), str)
        or len(plan["plan_hash"]) != 64
    ):
        raise RuntimeError("blind plan is not the frozen 81-scenario population")
    if (
        exclusion_audit.get("format")
        != "aios.surrogate-blind-plan-exclusion-audit.v1"
        or exclusion_audit.get("plan_hash") != plan["plan_hash"]
        or exclusion_audit.get("nonbaseline_overlap_count") != 0
        or exclusion_audit.get("historical_test_read") is not False
        or exclusion_audit.get("response_data_read") is not False
    ):
        raise RuntimeError("blind plan exclusion audit is unsafe")
    economics_lock = json.loads(args.economics_lock.read_text(encoding="utf-8"))
    if (
        economics_lock.get("historical_test_read") is not False
        or economics_lock.get("response_data_read") is not False
        or economics_lock.get("plan_hash") != plan["plan_hash"]
    ):
        raise RuntimeError("economics lock is unsafe or belongs to another plan")
    baseline = load_direct_npv_head(args.baseline_head)
    candidate = load_direct_npv_head(args.candidate_head)
    physical_weight = float(getattr(candidate, "physical_npv_weight", 0.0))
    if physical_weight > 0.0:
        if args.candidate_physical_npv is None:
            raise RuntimeError("physical blend requires locked physical NPV")
        physical_npv = json.loads(
            args.candidate_physical_npv.read_text(encoding="utf-8")
        )
        physical_rows = physical_npv.get("rows")
        if (
            physical_npv.get("format")
            != "aios.surrogate-blind-physical-npv.v1"
            or physical_npv.get("response_data_read") is not False
            or physical_npv.get("historical_test_read") is not False
            or physical_npv.get("frozen_before_blind_responses") is not True
            or physical_npv.get("plan_hash") != plan["plan_hash"]
            or physical_npv.get("ensemble_version")
            != getattr(candidate, "physical_ensemble_version", "")
            or not isinstance(physical_rows, list)
            or len(physical_rows) != len(scenarios)
            or len({row.get("scenario_id") for row in physical_rows})
            != len(scenarios)
        ):
            raise RuntimeError("locked physical NPV is unsafe or incompatible")
    elif args.candidate_physical_npv is not None:
        raise RuntimeError("non-blended candidate must not receive physical NPV")
    context = ModelZFeatureArtifact.load(args.feature_context)
    for head in (baseline, candidate):
        validate_direct_npv_head_context(
            head,
            context_dataset_hash=context.dataset_hash,
            feature_context_sha256=input_sha256["feature_context"],
        )
    if (
        baseline.wells != candidate.wells
        or baseline.static_feature_names != candidate.static_feature_names
    ):
        raise RuntimeError("baseline/candidate feature axes differ")
    locked_target_hash = economics_lock.get("target_provenance_sha256", "")
    candidate_target_hash = getattr(candidate, "target_provenance_hash", "")
    if (candidate_target_hash or locked_target_hash) and (
        candidate_target_hash != locked_target_hash
    ):
        raise RuntimeError("candidate target differs from blind economics lock")
    protocol = {
        "format": "aios.surrogate-blind-promotion-protocol.v2",
        "frozen_before_first_successful_blind_response": True,
        "historical_test_allowed": False,
        "plan": {
            "seed": plan["seed"],
            "plan_hash": plan["plan_hash"],
            "plan_sha256": input_sha256["plan"],
            "exclusion_audit_sha256": input_sha256["exclusion_audit"],
            "primary_excluded_scenario_ids": exclusion_audit.get(
                "allowed_baseline_overlaps", []
            ),
            "expected_scenarios": len(scenarios),
        },
        "baseline": _head_record(args.baseline_head, baseline),
        "candidate": _head_record(args.candidate_head, candidate),
        "economics_lock_sha256": input_sha256["economics_lock"],
        "target_provenance_hash": locked_target_hash,
        "feature_context_sha256": input_sha256["feature_context"],
        "physical_pipeline": physical_pipeline,
        "bootstrap": {
            "method": "paired family-stratified percentile bootstrap",
            "seed": PRIMARY_BOOTSTRAP_SEED,
            "replicates": args.bootstrap_replicates,
        },
        "promotion_gate": {
            "complete_clean_dataset": True,
            "candidate_mae_strictly_lower": True,
            "mae_improvement_ci95_low_strictly_positive": True,
            "spearman_point_difference_min": SPEARMAN_POINT_NONINFERIORITY,
            "spearman_ci95_difference_min": SPEARMAN_CI_NONINFERIORITY,
        },
        "optimizer_ranking_gate": {
            "true_best_rank_max": TRUE_BEST_RANK_MAX,
            "precision_at_5_difference_min": PRECISION_AT_5_DIFFERENCE_MIN,
        },
        "primary_population": "unique non-overlapping canonical_schedule_hash",
    }
    if args.candidate_physical_npv is not None:
        protocol["candidate"]["physical_npv_predictions_sha256"] = input_sha256[
            "candidate_physical_npv"
        ]
    _assert_response_free(args.dataset_root)
    final_sha256 = {
        "plan": _sha256(plan_path),
        "exclusion_audit": _sha256(exclusion_audit_path),
        "baseline_head": _sha256(args.baseline_head),
        "candidate_head": _sha256(args.candidate_head),
        "feature_context": _sha256(args.feature_context),
        "economics_lock": _sha256(args.economics_lock),
    }
    if args.candidate_physical_npv is not None:
        final_sha256["candidate_physical_npv"] = _sha256(
            args.candidate_physical_npv
        )
    if final_sha256 != input_sha256:
        raise RuntimeError("blind protocol inputs changed during freeze")
    if physical_pipeline_record(
        args.model_dir, opm_image=args.opm_image
    ) != physical_pipeline:
        raise RuntimeError("physical pipeline changed during protocol freeze")
    _write(args.output, protocol)
    print(f"frozen blind protocol written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
