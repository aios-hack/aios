"""Atomically switch the production NPV head only after a valid blind gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

if __package__:
    from tools.surrogate_evaluate_blind_npv import (
        _arrays,
        _bootstrap,
        _family_diagnostics,
        _promotion_gates,
        _score,
        _unique_rows,
    )
else:
    from surrogate_evaluate_blind_npv import (
        _arrays,
        _bootstrap,
        _family_diagnostics,
        _promotion_gates,
        _score,
        _unique_rows,
    )

from surrogate.npv_block_head import load_direct_npv_head

REQUIRED_GATES = {
    "complete_clean_dataset",
    "candidate_mae_lower",
    "mae_improvement_ci95_low_positive",
    "spearman_point_noninferior",
    "spearman_ci95_noninferior",
}
OPTIMIZER_GATES = {
    "candidate_true_best_in_top5",
    "candidate_precision_at5_noninferior",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--blind-report", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--locked-predictions", type=Path, required=True)
    parser.add_argument("--economics-lock", type=Path, required=True)
    parser.add_argument("--candidate-head", type=Path, required=True)
    parser.add_argument("--production-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any], *, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(f"refusing to overwrite decision artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_decision(comparison: dict[str, Any], protocol: dict[str, Any]) -> bool:
    if (
        protocol.get("format")
        not in {
            "aios.surrogate-blind-promotion-protocol.v1",
            "aios.surrogate-blind-promotion-protocol.v2",
        }
        or protocol.get("frozen_before_first_successful_blind_response") is not True
        or protocol.get("historical_test_allowed") is not False
    ):
        raise RuntimeError("invalid frozen promotion protocol")
    if comparison.get("format") != "aios.surrogate-blind-npv-comparison.v1":
        raise RuntimeError("unsupported blind comparison")
    if comparison.get("historical_test_read") is not False:
        raise RuntimeError("blind comparison may have read historical test")
    if comparison.get("blind_plan_hash") != protocol["plan"]["plan_hash"]:
        raise RuntimeError("comparison/protocol plan hashes differ")
    if comparison["baseline"]["version"] != protocol["baseline"]["model_version"]:
        raise RuntimeError("comparison baseline version differs")
    if comparison["candidate"]["version"] != protocol["candidate"]["model_version"]:
        raise RuntimeError("comparison candidate version differs")
    gates = comparison.get("promotion_gates")
    required_gates = REQUIRED_GATES | (
        OPTIMIZER_GATES if protocol.get("optimizer_ranking_gate") else set()
    )
    if not isinstance(gates, dict) or set(gates) != required_gates:
        raise RuntimeError("comparison promotion gates differ from implementation")
    bootstrap = comparison["bootstrap"]
    frozen_bootstrap = protocol["bootstrap"]
    if (
        bootstrap["seed"] != frozen_bootstrap["seed"]
        or bootstrap["replicates"] != frozen_bootstrap["replicates"]
    ):
        raise RuntimeError("comparison bootstrap settings differ")
    v2_metrics = comparison["baseline"]["metrics"]
    v3_metrics = comparison["candidate"]["metrics"]
    rho2 = v2_metrics["ranking"]["spearman_rank_correlation"]
    rho3 = v3_metrics["ranking"]["spearman_rank_correlation"]
    thresholds = protocol["promotion_gate"]
    expected_gates = {
        "complete_clean_dataset": (
            comparison.get("raw_row_count") == protocol["plan"]["expected_scenarios"]
            and comparison.get("unique_schedule_count", 0) > 1
            and isinstance(comparison.get("blind_dataset_hash"), str)
            and len(comparison["blind_dataset_hash"]) == 64
        ),
        "candidate_mae_lower": v3_metrics["mae_rub"] < v2_metrics["mae_rub"],
        "mae_improvement_ci95_low_positive": (
            bootstrap["mae_improvement_v2_minus_v3_rub"]["ci95_low"] > 0.0
        ),
        "spearman_point_noninferior": (
            rho3 - rho2 >= thresholds["spearman_point_difference_min"]
        ),
        "spearman_ci95_noninferior": (
            bootstrap["spearman_difference_v3_minus_v2"]["ci95_low"]
            >= thresholds["spearman_ci95_difference_min"]
        ),
    }
    optimizer_gate = protocol.get("optimizer_ranking_gate")
    if optimizer_gate is not None:
        expected_optimizer = _promotion_gates(
            v2_metrics,
            v3_metrics,
            bootstrap,
            optimizer_ranking_gate=optimizer_gate,
        )
        expected_gates.update(
            {name: expected_optimizer[name] for name in OPTIMIZER_GATES}
        )
    if gates != expected_gates:
        raise RuntimeError("reported promotion gates do not match recomputation")
    all_gates = all(expected_gates.values())
    if comparison.get("promote_candidate") is not all_gates:
        raise RuntimeError("comparison promotion verdict is inconsistent")
    return all_gates


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _validate_evidence(
    comparison: dict[str, Any],
    blind: dict[str, Any],
    locked: dict[str, Any],
    protocol: dict[str, Any],
) -> None:
    """Recompute the comparison from its rows before allowing deployment."""

    expected_count = protocol["plan"]["expected_scenarios"]
    if (
        blind.get("format") != "aios.surrogate-blind-dataset.v1"
        or blind.get("n_scenarios") != expected_count
        or blind.get("n_failed") != 0
        or blind.get("n_skipped") != 0
        or blind.get("plan_hash") != protocol["plan"]["plan_hash"]
        or blind.get("dataset_hash") != comparison.get("blind_dataset_hash")
    ):
        raise RuntimeError("blind report is not the complete frozen population")
    if (
        locked.get("format") != "aios.surrogate-locked-blind-predictions.v1"
        or locked.get("response_data_read") is not False
        or locked.get("historical_test_read") is not False
        or locked.get("plan_hash") != protocol["plan"]["plan_hash"]
        or locked.get("protocol_sha256") != comparison.get("protocol_sha256")
        or locked.get("baseline_version") != comparison["baseline"]["version"]
        or locked.get("candidate_version") != comparison["candidate"]["version"]
        or locked.get("n_scenarios") != expected_count
    ):
        raise RuntimeError("locked prediction header differs from frozen evidence")
    identities = blind.get("scenario_identity")
    rows = comparison.get("rows")
    locked_rows = locked.get("rows")
    if not all(isinstance(item, list) for item in (identities, rows, locked_rows)):
        raise RuntimeError("blind evidence rows are missing")
    if not (len(identities) == len(rows) == len(locked_rows) == expected_count):
        raise RuntimeError("blind evidence row counts differ")

    def unique_index(
        items: list[dict[str, Any]], label: str
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise TypeError(f"invalid {label} row")
            scenario_id = item.get("scenario_id")
            if not isinstance(scenario_id, str) or scenario_id in result:
                raise RuntimeError(f"duplicate or invalid {label} scenario id")
            result[scenario_id] = item
        return result

    identity_by_id = unique_index(identities, "blind identity")
    row_by_id = unique_index(rows, "comparison")
    locked_by_id = unique_index(locked_rows, "locked prediction")
    if not (set(identity_by_id) == set(row_by_id) == set(locked_by_id)):
        raise RuntimeError("blind evidence scenario ids differ")

    for scenario_id, row in row_by_id.items():
        identity = identity_by_id[scenario_id]
        prediction = locked_by_id[scenario_id]
        for field in ("family", "canonical_schedule_hash"):
            if row.get(field) != identity.get(field) or row.get(
                field
            ) != prediction.get(field):
                raise RuntimeError(f"{scenario_id}: blind {field} differs")
        if row.get("response_hash") != identity.get("response_hash"):
            raise RuntimeError(f"{scenario_id}: blind response hash differs")
        for field in ("actual_npv_rub", "v2_npv_rub", "v3_npv_rub"):
            if not _finite_number(row.get(field)):
                raise RuntimeError(f"{scenario_id}: invalid comparison {field}")
        for field in ("v2_npv_rub", "v3_npv_rub"):
            if row[field] != prediction.get(field):
                raise RuntimeError(f"{scenario_id}: locked {field} differs")

    excluded_primary_ids = set(
        protocol.get("plan", {}).get("primary_excluded_scenario_ids", [])
    )
    if comparison.get("primary_excluded_scenario_ids", []) != sorted(
        excluded_primary_ids
    ):
        raise RuntimeError("comparison primary exclusions differ from protocol")
    if not excluded_primary_ids <= set(row_by_id):
        raise RuntimeError("protocol excludes unknown primary scenario ids")
    primary_rows = [
        row for row in rows if row["scenario_id"] not in excluded_primary_ids
    ]
    unique = _unique_rows(primary_rows)
    if (
        comparison.get("primary_population")
        != protocol.get("primary_population", "unique canonical_schedule_hash")
        or comparison.get("raw_row_count") != len(rows)
        or comparison.get("unique_schedule_count") != len(unique)
        or comparison.get("duplicate_row_count")
        != len(primary_rows) - len(unique)
    ):
        raise RuntimeError("comparison population accounting differs")

    raw_actual, raw_v2, raw_v3 = _arrays(rows)
    actual, v2, v3 = _arrays(unique)
    expected_v2 = _score(actual, v2)
    expected_v3 = _score(actual, v3)
    if comparison["baseline"]["metrics"] != expected_v2:
        raise RuntimeError("reported v2 metrics differ from row recomputation")
    if comparison["candidate"]["metrics"] != expected_v3:
        raise RuntimeError("reported v3 metrics differ from row recomputation")
    if comparison.get("raw_metrics") != {
        "baseline": _score(raw_actual, raw_v2),
        "candidate": _score(raw_actual, raw_v3),
    }:
        raise RuntimeError("reported raw metrics differ from row recomputation")
    if comparison.get("family_diagnostics_unique") != _family_diagnostics(unique):
        raise RuntimeError("reported family diagnostics differ from row recomputation")
    expected_bootstrap = _bootstrap(
        unique, replicates=protocol["bootstrap"]["replicates"]
    )
    if comparison.get("bootstrap") != expected_bootstrap:
        raise RuntimeError("reported bootstrap differs from row recomputation")
    if comparison.get("promotion_gates") != _promotion_gates(
        expected_v2,
        expected_v3,
        expected_bootstrap,
        optimizer_ranking_gate=protocol.get("optimizer_ranking_gate"),
    ):
        raise RuntimeError("reported gates differ from row recomputation")


def main() -> int:
    args = _parser().parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite decision artifact: {args.output}")
    comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
    blind = json.loads(args.blind_report.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    locked = json.loads(args.locked_predictions.read_text(encoding="utf-8"))
    economics_lock = json.loads(args.economics_lock.read_text(encoding="utf-8"))
    production = json.loads(args.production_manifest.read_text(encoding="utf-8"))
    if production.get("format") != "aios.surrogate-production-pointer.v1":
        raise RuntimeError("unsupported production manifest")
    if comparison.get("protocol_sha256") != _sha256(args.protocol):
        raise RuntimeError("comparison protocol bytes differ")
    if comparison.get("blind_report_sha256") != _sha256(args.blind_report):
        raise RuntimeError("comparison blind report differs")
    if comparison.get("locked_predictions_sha256") != _sha256(args.locked_predictions):
        raise RuntimeError("comparison locked predictions differ")
    if comparison.get("economics_lock_sha256") != _sha256(args.economics_lock):
        raise RuntimeError("comparison economics lock differs")
    candidate = load_direct_npv_head(args.candidate_head)
    if (
        candidate.version != protocol["candidate"]["model_version"]
        or _sha256(args.candidate_head) != protocol["candidate"]["checkpoint_sha256"]
    ):
        raise RuntimeError("candidate checkpoint differs from protocol")
    for field in ("target_provenance_hash", "feature_context_sha256"):
        actual = getattr(candidate, field, "")
        if actual and protocol["candidate"].get(field) != actual:
            raise RuntimeError(f"candidate {field} differs from protocol")
    locked_target_hash = economics_lock.get("target_provenance_sha256", "")
    if (candidate.target_provenance_hash or locked_target_hash) and (
        candidate.target_provenance_hash != locked_target_hash
        or protocol.get("target_provenance_hash", "") != locked_target_hash
    ):
        raise RuntimeError("candidate target differs from blind economics lock")
    current_head = args.production_manifest.parent / production["npv_head"]
    current = load_direct_npv_head(current_head)
    if (
        current.version != protocol["baseline"]["model_version"]
        or _sha256(current_head) != protocol["baseline"]["checkpoint_sha256"]
        or production.get("active_economic_model_version") != current.version
    ):
        raise RuntimeError("active production head is not the frozen baseline")
    for field in ("target_provenance_hash", "feature_context_sha256"):
        actual = getattr(current, field, "")
        if actual and protocol["baseline"].get(field) != actual:
            raise RuntimeError(f"baseline {field} differs from protocol")

    _validate_evidence(comparison, blind, locked, protocol)
    promote = _validate_decision(comparison, protocol)
    decision = {
        "format": "aios.surrogate-blind-promotion-decision.v1",
        "comparison": str(args.comparison),
        "comparison_sha256": _sha256(args.comparison),
        "blind_report_sha256": _sha256(args.blind_report),
        "protocol_sha256": _sha256(args.protocol),
        "locked_predictions_sha256": _sha256(args.locked_predictions),
        "economics_lock_sha256": _sha256(args.economics_lock),
        "production_manifest": str(args.production_manifest),
        "production_manifest_sha256_before": _sha256(args.production_manifest),
        "baseline_version": current.version,
        "candidate_version": candidate.version,
        "candidate_target_provenance_hash": candidate.target_provenance_hash,
        "promoted": promote,
        "promotion_gates": comparison["promotion_gates"],
    }
    if promote:
        updated = dict(production)
        updated["npv_head"] = os.path.relpath(
            args.candidate_head, args.production_manifest.parent
        )
        updated["active_economic_model_version"] = candidate.version
        if candidate.target_provenance_hash:
            updated["active_economic_target_provenance_hash"] = (
                candidate.target_provenance_hash
            )
        else:
            updated.pop("active_economic_target_provenance_hash", None)
        updated["promotion_basis"] = {
            "format": comparison["format"],
            "comparison_sha256": decision["comparison_sha256"],
            "blind_dataset_hash": comparison["blind_dataset_hash"],
            "blind_plan_hash": comparison["blind_plan_hash"],
            "promotion_gates": comparison["promotion_gates"],
        }
        _write_json(args.production_manifest, updated, replace=True)
        decision["production_manifest_sha256_after"] = _sha256(args.production_manifest)
    _write_json(args.output, decision, replace=False)
    print(
        "candidate promoted" if promote else "candidate rejected; v2 remains active",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
