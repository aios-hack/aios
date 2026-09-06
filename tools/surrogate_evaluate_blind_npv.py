"""One-time paired v2/v3 evaluation on a completed blind OPM dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

if __package__:
    from tools.surrogate_evaluate_ensemble_npv import _cache_index
else:
    from surrogate_evaluate_ensemble_npv import _cache_index

from bridge.dataset import dataset_base_schedule
from bridge.dataset_plan import PlanConfig, build_plan, materialize
from bridge.opm_deck import OpmDeckEmitter
from bridge.response_loader import ResponseLoader, load_density_by_pvtnum
from bridge.summary import build_summary_plan
from config.schema import default_policies
from contracts import hash_schedule
from economics import analyze_base_case, load_normatives, methodology_version_hash
from schedule import parse_schedule
from surrogate.features import ScheduleFeatureizer
from surrogate.metrics import ranking_metrics
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.npv_block_head import (
    load_direct_npv_head,
    validate_direct_npv_head_context,
)
from surrogate.npv_target import TARGET_PROVENANCE_FORMAT, validate_target_provenance

PRIMARY_BOOTSTRAP_SEED = 20260827
SPEARMAN_POINT_NONINFERIORITY = -0.02
SPEARMAN_CI_NONINFERIORITY = -0.03
TRUE_BEST_RANK_MAX = 5
PRECISION_AT_5_DIFFERENCE_MIN = -0.2
ECONOMICS_LOCK_SOURCES = {
    "bridge/response_loader.py",
    "bridge/summary.py",
    "config/__init__.py",
    "config/normatives.py",
    "config/schema.py",
    "contracts/__init__.py",
    "contracts/config.py",
    "contracts/economics.py",
    "contracts/hashing.py",
    "contracts/policy.py",
    "contracts/response.py",
    "contracts/schedule.py",
    "economics/__init__.py",
    "economics/base_case.py",
    "economics/decomposition.py",
    "economics/esp.py",
    "economics/fund.py",
    "economics/ledger.py",
    "economics/methodology_hash.py",
    "economics/normatives_io.py",
    "economics/npv.py",
    "schedule/__init__.py",
    "schedule/lossless.py",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--blind-report", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--locked-predictions", type=Path, required=True)
    parser.add_argument("--economics-lock", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--baseline-head", type=Path, required=True)
    parser.add_argument("--candidate-head", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    return parser


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_protocol(
    protocol: dict[str, Any],
    *,
    baseline_path: Path,
    baseline: object,
    candidate_path: Path,
    candidate: object,
    blind: dict[str, Any],
    bootstrap_replicates: int,
) -> None:
    if protocol.get("format") not in {
        "aios.surrogate-blind-promotion-protocol.v1",
        "aios.surrogate-blind-promotion-protocol.v2",
    }:
        raise RuntimeError("unsupported blind protocol")
    if not protocol.get("frozen_before_first_successful_blind_response"):
        raise RuntimeError("blind protocol was not frozen before responses")
    if protocol.get("historical_test_allowed") is not False:
        raise RuntimeError("blind protocol does not forbid historical test")
    plan = protocol["plan"]
    if plan["plan_hash"] != blind.get("plan_hash"):
        raise RuntimeError("protocol/blind plan hashes differ")
    if plan["expected_scenarios"] != blind.get("n_scenarios"):
        raise RuntimeError("protocol/blind scenario counts differ")
    expected_bootstrap = protocol["bootstrap"]
    if (
        expected_bootstrap["seed"] != PRIMARY_BOOTSTRAP_SEED
        or expected_bootstrap["replicates"] != bootstrap_replicates
    ):
        raise RuntimeError("bootstrap settings differ from frozen protocol")
    gate = protocol["promotion_gate"]
    if (
        gate["spearman_point_difference_min"] != SPEARMAN_POINT_NONINFERIORITY
        or gate["spearman_ci95_difference_min"] != SPEARMAN_CI_NONINFERIORITY
    ):
        raise RuntimeError("promotion thresholds differ from frozen protocol")
    optimizer_gate = protocol.get("optimizer_ranking_gate")
    if optimizer_gate is not None and optimizer_gate != {
        "true_best_rank_max": TRUE_BEST_RANK_MAX,
        "precision_at_5_difference_min": PRECISION_AT_5_DIFFERENCE_MIN,
    }:
        raise RuntimeError("optimizer ranking thresholds differ from protocol")
    for name, path, head in (
        ("baseline", baseline_path, baseline),
        ("candidate", candidate_path, candidate),
    ):
        expected = protocol[name]
        if expected["model_version"] != head.version:
            raise RuntimeError(f"{name} model version differs from protocol")
        if expected["checkpoint_sha256"] != _sha256(path):
            raise RuntimeError(f"{name} checkpoint hash differs from protocol")
        for field in (
            "target_provenance_hash",
            "feature_context_sha256",
            "physical_npv_weight",
            "physical_ensemble_version",
            "physical_blend_provenance_hash",
        ):
            actual = getattr(head, field, "")
            if actual and expected.get(field) != actual:
                raise RuntimeError(f"{name} {field} differs from protocol")


def _validate_economics_lock(
    lock: dict[str, Any],
    *,
    project_root: Path,
    model_schedule: Path,
    normatives: Path,
    plan_hash: str,
) -> None:
    if lock.get("format") != "aios.surrogate-blind-economics-lock.v1":
        raise RuntimeError("unsupported blind economics lock")
    if (
        lock.get("historical_test_read") is not False
        or lock.get("response_data_read") is not False
        or lock.get("plan_hash") != plan_hash
    ):
        raise RuntimeError("unsafe blind economics lock provenance")
    source_hashes = lock.get("source_sha256")
    if (
        not isinstance(source_hashes, dict)
        or set(source_hashes) != ECONOMICS_LOCK_SOURCES
    ):
        raise RuntimeError("economics lock source set differs")
    for relative, expected in source_hashes.items():
        if _sha256(project_root / relative) != expected:
            raise RuntimeError(f"legacy economics source changed: {relative}")
    if methodology_version_hash() != lock.get("methodology_version_hash"):
        raise RuntimeError("legacy methodology version hash changed")
    if _sha256(model_schedule) != lock.get("model_schedule_sha256"):
        raise RuntimeError("legacy economics model schedule changed")
    if _sha256(normatives) != lock.get("normatives_sha256"):
        raise RuntimeError("legacy economics normatives changed")
    if lock.get("target_provenance_sha256"):
        provenance = {
            "format": TARGET_PROVENANCE_FORMAT,
            "target": "npv_methodology_rub",
            "source_sha256": source_hashes,
            "methodology_version_hash": lock["methodology_version_hash"],
            "model_schedule_sha256": lock["model_schedule_sha256"],
            "normatives_sha256": lock["normatives_sha256"],
            "target_provenance_sha256": lock["target_provenance_sha256"],
        }
        validate_target_provenance(provenance)


def _validate_locked_predictions(
    locked: dict[str, Any],
    *,
    expected_scenarios: dict[str, tuple[str, str]],
    plan_hash: str,
    protocol_sha256: str,
    baseline_version: str,
    candidate_version: str,
    baseline_target_provenance_hash: str = "",
    candidate_target_provenance_hash: str = "",
    baseline_feature_context_sha256: str = "",
    candidate_feature_context_sha256: str = "",
    baseline_physical_npv_sha256: str = "",
    baseline_physical_npv_weight: float = 0.0,
    candidate_physical_npv_sha256: str = "",
    candidate_physical_npv_weight: float = 0.0,
) -> dict[str, dict[str, Any]]:
    if locked.get("format") != "aios.surrogate-locked-blind-predictions.v1":
        raise RuntimeError("unsupported locked prediction artifact")
    if locked.get("response_data_read") is not False:
        raise RuntimeError("predictions were not locked response-free")
    if locked.get("historical_test_read") is not False:
        raise RuntimeError("locked predictions may have read historical test")
    if locked.get("plan_hash") != plan_hash:
        raise RuntimeError("locked prediction/plan hashes differ")
    if (
        locked.get("protocol_sha256") != protocol_sha256
        or locked.get("baseline_version") != baseline_version
        or locked.get("candidate_version") != candidate_version
    ):
        raise RuntimeError("locked prediction provenance differs")
    for field, expected in (
        ("baseline_target_provenance_hash", baseline_target_provenance_hash),
        ("candidate_target_provenance_hash", candidate_target_provenance_hash),
        ("baseline_feature_context_sha256", baseline_feature_context_sha256),
        ("candidate_feature_context_sha256", candidate_feature_context_sha256),
    ):
        if expected and locked.get(field) != expected:
            raise RuntimeError(f"locked prediction {field} differs")
    if candidate_physical_npv_sha256 and (
        locked.get("candidate_physical_npv_sha256")
        != candidate_physical_npv_sha256
        or locked.get("candidate_physical_npv_weight")
        != candidate_physical_npv_weight
    ):
        raise RuntimeError("locked physical blend provenance differs")
    if baseline_physical_npv_sha256 and (
        locked.get("baseline_physical_npv_sha256")
        != baseline_physical_npv_sha256
        or locked.get("baseline_physical_npv_weight")
        != baseline_physical_npv_weight
    ):
        raise RuntimeError("locked baseline physical blend provenance differs")
    rows = locked.get("rows")
    if not isinstance(rows, list):
        raise TypeError("locked prediction rows are missing")
    if locked.get("n_scenarios") != len(rows) or len(rows) != len(expected_scenarios):
        raise RuntimeError("locked prediction scenario count differs")
    locked_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        scenario_id = row.get("scenario_id")
        if scenario_id in locked_by_id:
            raise RuntimeError(f"duplicate locked prediction id: {scenario_id}")
        if scenario_id not in expected_scenarios:
            raise RuntimeError(f"unexpected locked prediction id: {scenario_id}")
        expected_family, expected_hash = expected_scenarios[scenario_id]
        if (
            row.get("family") != expected_family
            or row.get("canonical_schedule_hash") != expected_hash
        ):
            raise RuntimeError(f"{scenario_id}: locked scenario identity differs")
        for field in ("v2_npv_rub", "v3_npv_rub"):
            value = row.get(field)
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise RuntimeError(f"{scenario_id}: invalid locked {field}")
        for weight, field in (
            (baseline_physical_npv_weight, "v2_direct_npv_rub"),
            (candidate_physical_npv_weight, "v3_direct_npv_rub"),
        ):
            if weight > 0.0:
                value = row.get(field)
                if type(value) not in (int, float) or not math.isfinite(
                    float(value)
                ):
                    raise RuntimeError(f"{scenario_id}: invalid locked {field}")
        if baseline_physical_npv_weight > 0.0:
            value = row.get("physical_npv_rub")
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise RuntimeError(
                    f"{scenario_id}: invalid locked physical_npv_rub"
                )
        locked_by_id[scenario_id] = row
    if set(locked_by_id) != set(expected_scenarios):
        raise RuntimeError("locked predictions do not cover blind plan")
    return locked_by_id


def _score(actual: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    actual_values = actual.tolist()
    predicted_values = predicted.tolist()
    actual_order = np.argsort(-actual, kind="stable")
    predicted_order = np.argsort(-predicted, kind="stable")
    true_best = int(actual_order[0])
    ranking = asdict(
        ranking_metrics(
            actual_values,
            predicted_values,
            k_values=(1, 3, 5, 10, 20, 40),
        )
    )
    # JSON object keys are always strings.  Canonicalize the two k-indexed
    # mappings before the evidence is written so an independently recomputed
    # score compares exactly with the deserialized artifact.
    for field in ("precision_at_k", "regret_at_k_rub"):
        ranking[field] = {str(k): value for k, value in ranking[field].items()}
    return {
        "ranking": ranking,
        "mae_rub": float(np.mean(np.abs(predicted - actual))),
        "rmse_rub": float(np.sqrt(np.mean(np.square(predicted - actual)))),
        "bias_rub": float(np.mean(predicted - actual)),
        "rank_of_true_best": int(np.flatnonzero(predicted_order == true_best)[0] + 1),
    }


def _plan_from_artifact(model_dir: Path, dataset_root: Path):
    payload = json.loads((dataset_root / "plan.json").read_text(encoding="utf-8"))
    counts = Counter(item["family"] for item in payload["scenarios"])
    config = PlanConfig(
        n_level_scenarios=counts["LEVELS"],
        n_unreachable_scenarios=counts["UNREACHABLE"],
        n_shutdown_scenarios=counts["SHUTDOWN"],
        n_conversion_scenarios=counts["CONVERSION"],
        include_baseline=bool(counts["BASELINE"]),
    )
    emitter = OpmDeckEmitter(model_dir)
    base = dataset_base_schedule(model_dir, emitter)
    plan = build_plan(base, seed=int(payload["seed"]), config=config)
    if plan.plan_hash != payload["plan_hash"]:
        raise RuntimeError("reconstructed blind plan hash differs")
    return emitter, base, plan


def _unique_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["canonical_schedule_hash"]].append(row)
    unique = []
    for schedule_hash, duplicates in sorted(grouped.items()):
        reference = duplicates[0]
        for other in duplicates[1:]:
            for field in ("actual_npv_rub", "v2_npv_rub", "v3_npv_rub"):
                if not math.isclose(
                    reference[field], other[field], rel_tol=0.0, abs_tol=1.0e-6
                ):
                    raise RuntimeError(
                        f"duplicate schedule {schedule_hash} has different {field}"
                    )
        unique.append(reference)
    return unique


def _arrays(rows: list[dict[str, Any]]):
    return (
        np.asarray([row["actual_npv_rub"] for row in rows]),
        np.asarray([row["v2_npv_rub"] for row in rows]),
        np.asarray([row["v3_npv_rub"] for row in rows]),
    )


def _family_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics = {}
    for family in sorted({row["family"] for row in rows}):
        subset = [row for row in rows if row["family"] == family]
        actual, v2, v3 = _arrays(subset)
        item: dict[str, Any] = {
            "n": len(subset),
            "v2_mae_rub": float(np.mean(np.abs(v2 - actual))),
            "v3_mae_rub": float(np.mean(np.abs(v3 - actual))),
            "mae_improvement_v2_minus_v3_rub": float(
                np.mean(np.abs(v2 - actual)) - np.mean(np.abs(v3 - actual))
            ),
        }
        if len(subset) >= 2:
            item["v2_spearman"] = _score(actual, v2)["ranking"][
                "spearman_rank_correlation"
            ]
            item["v3_spearman"] = _score(actual, v3)["ranking"][
                "spearman_rank_correlation"
            ]
        diagnostics[family] = item
    return diagnostics


def _bootstrap(rows: list[dict[str, Any]], *, replicates: int) -> dict[str, Any]:
    if replicates < 1_000:
        raise ValueError("at least 1,000 bootstrap replicates are required")
    by_family: dict[str, np.ndarray] = {}
    for family in sorted({row["family"] for row in rows}):
        by_family[family] = np.asarray(
            [index for index, row in enumerate(rows) if row["family"] == family]
        )
    actual, v2, v3 = _arrays(rows)
    rng = np.random.default_rng(PRIMARY_BOOTSTRAP_SEED)
    mae_improvement = np.empty(replicates)
    spearman_difference = np.empty(replicates)
    for replicate in range(replicates):
        sampled = np.concatenate(
            [
                rng.choice(indices, size=len(indices), replace=True)
                for indices in by_family.values()
            ]
        )
        sampled_actual = actual[sampled]
        sampled_v2 = v2[sampled]
        sampled_v3 = v3[sampled]
        mae_improvement[replicate] = np.mean(
            np.abs(sampled_v2 - sampled_actual)
        ) - np.mean(np.abs(sampled_v3 - sampled_actual))
        rho2 = ranking_metrics(
            sampled_actual.tolist(), sampled_v2.tolist()
        ).spearman_rank_correlation
        rho3 = ranking_metrics(
            sampled_actual.tolist(), sampled_v3.tolist()
        ).spearman_rank_correlation
        spearman_difference[replicate] = rho3 - rho2

    def summary(values: np.ndarray) -> dict[str, float]:
        low, high = np.quantile(values, (0.025, 0.975))
        return {
            "median": float(np.median(values)),
            "mean": float(np.mean(values)),
            "ci95_low": float(low),
            "ci95_high": float(high),
            "probability_positive": float(np.mean(values > 0.0)),
        }

    return {
        "method": "paired family-stratified percentile bootstrap",
        "seed": PRIMARY_BOOTSTRAP_SEED,
        "replicates": replicates,
        "family_counts": {name: len(indices) for name, indices in by_family.items()},
        "mae_improvement_v2_minus_v3_rub": summary(mae_improvement),
        "spearman_difference_v3_minus_v2": summary(spearman_difference),
    }


def _promotion_gates(
    v2_metrics: dict[str, Any],
    v3_metrics: dict[str, Any],
    bootstrap: dict[str, Any],
    *,
    optimizer_ranking_gate: dict[str, Any] | None = None,
) -> dict[str, bool]:
    mae_ci = bootstrap["mae_improvement_v2_minus_v3_rub"]
    rho_ci = bootstrap["spearman_difference_v3_minus_v2"]
    rho2 = v2_metrics["ranking"]["spearman_rank_correlation"]
    rho3 = v3_metrics["ranking"]["spearman_rank_correlation"]
    gates = {
        "complete_clean_dataset": True,
        "candidate_mae_lower": v3_metrics["mae_rub"] < v2_metrics["mae_rub"],
        "mae_improvement_ci95_low_positive": mae_ci["ci95_low"] > 0.0,
        "spearman_point_noninferior": (rho3 - rho2 >= SPEARMAN_POINT_NONINFERIORITY),
        "spearman_ci95_noninferior": (rho_ci["ci95_low"] >= SPEARMAN_CI_NONINFERIORITY),
    }
    if optimizer_ranking_gate is not None:
        if optimizer_ranking_gate != {
            "true_best_rank_max": TRUE_BEST_RANK_MAX,
            "precision_at_5_difference_min": PRECISION_AT_5_DIFFERENCE_MIN,
        }:
            raise RuntimeError("optimizer ranking gates differ from implementation")
        precision2_by_k = v2_metrics["ranking"]["precision_at_k"]
        precision3_by_k = v3_metrics["ranking"]["precision_at_k"]
        precision2 = precision2_by_k.get(5, precision2_by_k.get("5"))
        precision3 = precision3_by_k.get(5, precision3_by_k.get("5"))
        if type(precision2) not in (int, float) or type(precision3) not in (
            int,
            float,
        ):
            raise RuntimeError("precision@5 metrics are missing")
        gates.update(
            {
                "candidate_true_best_in_top5": (
                    v3_metrics["rank_of_true_best"] <= TRUE_BEST_RANK_MAX
                ),
                "candidate_precision_at5_noninferior": (
                    precision3 - precision2 >= PRECISION_AT_5_DIFFERENCE_MIN
                ),
            }
        )
    return gates


def main() -> int:
    args = _parser().parse_args()
    blind = json.loads(args.blind_report.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    locked = json.loads(args.locked_predictions.read_text(encoding="utf-8"))
    economics_lock = json.loads(args.economics_lock.read_text(encoding="utf-8"))
    if protocol.get("economics_lock_sha256") not in {
        None,
        _sha256(args.economics_lock),
    }:
        raise RuntimeError("protocol economics lock bytes differ")
    if blind.get("format") != "aios.surrogate-blind-dataset.v1":
        raise RuntimeError("unsupported blind report")
    if (
        blind.get("n_scenarios") != 81
        or blind.get("n_failed")
        or blind.get("n_skipped")
    ):
        raise RuntimeError("blind dataset is not complete and clean")
    emitter, base, plan = _plan_from_artifact(args.model_dir, args.dataset_root)
    if plan.plan_hash != blind.get("plan_hash"):
        raise RuntimeError("blind report/plan hashes differ")
    frozen_plan_sha256 = protocol.get("plan", {}).get("plan_sha256")
    if frozen_plan_sha256 and frozen_plan_sha256 != _sha256(
        args.dataset_root / "plan.json"
    ):
        raise RuntimeError("blind plan bytes differ from frozen protocol")
    frozen_audit_sha256 = protocol.get("plan", {}).get(
        "exclusion_audit_sha256"
    )
    if frozen_audit_sha256 and frozen_audit_sha256 != _sha256(
        args.dataset_root / "plan_exclusion_audit.json"
    ):
        raise RuntimeError("blind exclusion audit differs from frozen protocol")
    _validate_economics_lock(
        economics_lock,
        project_root=Path(__file__).resolve().parents[1],
        model_schedule=args.model_dir / "Model_Z_sch.inc",
        normatives=args.normatives,
        plan_hash=plan.plan_hash,
    )
    identities = blind["scenario_identity"]
    if len(identities) != len(plan.specs):
        raise RuntimeError("blind identities do not cover plan")
    identity_by_id = {item["scenario_id"]: item for item in identities}
    if set(identity_by_id) != {item.scenario_id for item in plan.specs}:
        raise RuntimeError("blind scenario ids do not cover reconstructed plan")

    context = ModelZFeatureArtifact.load(args.feature_context)
    v2 = load_direct_npv_head(args.baseline_head)
    v3 = load_direct_npv_head(args.candidate_head)
    _validate_protocol(
        protocol,
        baseline_path=args.baseline_head,
        baseline=v2,
        candidate_path=args.candidate_head,
        candidate=v3,
        blind=blind,
        bootstrap_replicates=args.bootstrap_replicates,
    )
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
    locked_target_hash = economics_lock.get("target_provenance_sha256", "")
    if (v3.target_provenance_hash or locked_target_hash) and (
        v3.target_provenance_hash != locked_target_hash
    ):
        raise RuntimeError("candidate target differs from blind economics lock")
    if protocol.get("target_provenance_hash", "") != locked_target_hash:
        raise RuntimeError("protocol target differs from blind economics lock")
    expected_scenarios = {}
    for spec in plan.specs:
        material = materialize(base, spec)
        expected_scenarios[spec.scenario_id] = (
            spec.family.value,
            hash_schedule(material.schedule),
        )
    locked_by_id = _validate_locked_predictions(
        locked,
        expected_scenarios=expected_scenarios,
        plan_hash=plan.plan_hash,
        protocol_sha256=_sha256(args.protocol),
        baseline_version=v2.version,
        candidate_version=v3.version,
        baseline_target_provenance_hash=v2.target_provenance_hash,
        candidate_target_provenance_hash=v3.target_provenance_hash,
        baseline_feature_context_sha256=v2.feature_context_sha256,
        candidate_feature_context_sha256=v3.feature_context_sha256,
        baseline_physical_npv_sha256=(
            protocol["candidate"].get("physical_npv_predictions_sha256", "")
            if float(getattr(v2, "physical_npv_weight", 0.0)) > 0.0
            else ""
        ),
        baseline_physical_npv_weight=float(
            getattr(v2, "physical_npv_weight", 0.0)
        ),
        candidate_physical_npv_sha256=protocol["candidate"].get(
            "physical_npv_predictions_sha256", ""
        ),
        candidate_physical_npv_weight=float(
            getattr(v3, "physical_npv_weight", 0.0)
        ),
    )
    cache = _cache_index(args.dataset_root)
    summary_plan = build_summary_plan(args.model_dir, emitter.source_wells)
    densities = load_density_by_pvtnum(args.model_dir)
    response_loader = ResponseLoader()
    featureizer = ScheduleFeatureizer()
    parsed = parse_schedule((args.model_dir / "Model_Z_sch.inc").read_bytes())
    normatives = load_normatives(args.normatives)
    policies = default_policies()
    rows = []
    for index, spec in enumerate(
        sorted(plan.specs, key=lambda item: item.scenario_id), start=1
    ):
        identity = identity_by_id[spec.scenario_id]
        material = materialize(base, spec)
        schedule_hash = identity["canonical_schedule_hash"]
        if hash_schedule(material.schedule) != schedule_hash:
            raise RuntimeError(f"{spec.scenario_id}: schedule hash differs")
        run = cache.get(schedule_hash)
        if run is None:
            raise RuntimeError(f"{spec.scenario_id}: blind cache entry missing")
        response = response_loader.load(run, summary_plan, material.schedule, densities)
        if response.response_hash != identity["response_hash"]:
            raise RuntimeError(f"{spec.scenario_id}: response hash differs")
        candidate = replace(
            featureizer.transform(material.schedule, context.context),
            lambda_edges=(),
        )
        locked_row = locked_by_id[spec.scenario_id]
        computed_v2_direct = v2.predict(candidate)
        computed_v3_direct = v3.predict(candidate)
        baseline_physical_weight = float(
            getattr(v2, "physical_npv_weight", 0.0)
        )
        physical_weight = float(getattr(v3, "physical_npv_weight", 0.0))
        locked_v2_direct = locked_row.get(
            "v2_direct_npv_rub", locked_row["v2_npv_rub"]
        )
        locked_v3_direct = locked_row.get(
            "v3_direct_npv_rub", locked_row["v3_npv_rub"]
        )
        if computed_v2_direct != locked_v2_direct or (
            computed_v3_direct != locked_v3_direct
        ):
            raise RuntimeError(f"{spec.scenario_id}: locked prediction differs")
        if baseline_physical_weight > 0.0 and "v2_direct_npv_rub" not in locked_row:
            raise RuntimeError(
                f"{spec.scenario_id}: locked baseline blend lacks direct component"
            )
        if physical_weight > 0.0 and "v3_direct_npv_rub" not in locked_row:
            raise RuntimeError(
                f"{spec.scenario_id}: locked physical blend lacks direct component"
            )
        if baseline_physical_weight > 0.0 or "physical_npv_rub" in locked_row:
            physical_npv = locked_row["physical_npv_rub"]
            if baseline_physical_weight > 0.0:
                computed_v2 = (
                    (1.0 - baseline_physical_weight) * computed_v2_direct
                    + baseline_physical_weight * physical_npv
                )
                if computed_v2 != locked_row["v2_npv_rub"]:
                    raise RuntimeError(
                        f"{spec.scenario_id}: locked baseline blend differs"
                    )
            if physical_weight > 0.0:
                computed_v3 = (
                    (1.0 - physical_weight) * computed_v3_direct
                    + physical_weight * physical_npv
                )
                if computed_v3 != locked_row["v3_npv_rub"]:
                    raise RuntimeError(
                        f"{spec.scenario_id}: locked candidate blend differs"
                    )
        actual = analyze_base_case(
            response,
            parsed.dates,
            parsed.t0_deck_date_index,
            normatives,
            policies,
        ).npv_methodology
        rows.append(
            {
                "scenario_id": spec.scenario_id,
                "family": spec.family.value,
                "canonical_schedule_hash": schedule_hash,
                "response_hash": response.response_hash,
                "actual_npv_rub": actual,
                "v2_npv_rub": locked_row["v2_npv_rub"],
                "v3_npv_rub": locked_row["v3_npv_rub"],
            }
        )
        if index == 1 or index % 10 == 0 or index == len(plan.specs):
            print(f"blind evaluation {index}/{len(plan.specs)}", flush=True)

    excluded_primary_ids = set(
        protocol.get("plan", {}).get("primary_excluded_scenario_ids", [])
    )
    if not excluded_primary_ids <= {row["scenario_id"] for row in rows}:
        raise RuntimeError("protocol excludes unknown primary scenario ids")
    primary_rows = [
        row for row in rows if row["scenario_id"] not in excluded_primary_ids
    ]
    unique = _unique_rows(primary_rows)
    raw_actual, raw_baseline, raw_candidate = _arrays(rows)
    actual, baseline, candidate = _arrays(unique)
    v2_metrics = _score(actual, baseline)
    v3_metrics = _score(actual, candidate)
    bootstrap = _bootstrap(unique, replicates=args.bootstrap_replicates)
    rho2 = v2_metrics["ranking"]["spearman_rank_correlation"]
    rho3 = v3_metrics["ranking"]["spearman_rank_correlation"]
    gates = _promotion_gates(
        v2_metrics,
        v3_metrics,
        bootstrap,
        optimizer_ranking_gate=protocol.get("optimizer_ranking_gate"),
    )
    report = {
        "format": "aios.surrogate-blind-npv-comparison.v1",
        "historical_test_read": False,
        "protocol": str(args.protocol),
        "protocol_sha256": _sha256(args.protocol),
        "locked_predictions": str(args.locked_predictions),
        "locked_predictions_sha256": _sha256(args.locked_predictions),
        "economics_lock": str(args.economics_lock),
        "economics_lock_sha256": _sha256(args.economics_lock),
        "blind_report": str(args.blind_report),
        "blind_report_sha256": _sha256(args.blind_report),
        "blind_dataset_hash": blind["dataset_hash"],
        "blind_plan_hash": blind["plan_hash"],
        "primary_population": protocol.get(
            "primary_population", "unique canonical_schedule_hash"
        ),
        "primary_excluded_scenario_ids": sorted(excluded_primary_ids),
        "baseline": {"version": v2.version, "metrics": v2_metrics},
        "candidate": {"version": v3.version, "metrics": v3_metrics},
        "raw_metrics": {
            "baseline": _score(raw_actual, raw_baseline),
            "candidate": _score(raw_actual, raw_candidate),
        },
        "family_diagnostics_unique": _family_diagnostics(unique),
        "raw_row_count": len(rows),
        "unique_schedule_count": len(unique),
        "duplicate_row_count": len(primary_rows) - len(unique),
        "bootstrap": bootstrap,
        "promotion_gates": gates,
        "promote_candidate": all(gates.values()),
        "rows": rows,
    }
    _write_json(args.output, report)
    print(
        f"blind v2 MAE={v2_metrics['mae_rub'] / 1e6:.2f}m "
        f"rho={rho2:.4f}; v3 MAE={v3_metrics['mae_rub'] / 1e6:.2f}m "
        f"rho={rho3:.4f}; promote={report['promote_candidate']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
