from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from tools.surrogate_apply_blind_promotion import (
    REQUIRED_GATES,
    _validate_decision,
    _validate_evidence,
)
from tools.surrogate_build_blind_dataset import _validate_execution_protocol
from tools.surrogate_cache_blind_features import _locked_direct_candidate_npv
from tools.surrogate_evaluate_blind_npv import (
    ECONOMICS_LOCK_SOURCES,
    _bootstrap,
    _family_diagnostics,
    _promotion_gates,
    _score,
    _sha256,
    _unique_rows,
    _validate_economics_lock,
    _validate_locked_predictions,
    _validate_protocol,
)
from tools.surrogate_finalize_blind_report import _verify
from tools.surrogate_freeze_blind_protocol import (
    _assert_response_free,
    _head_record,
    physical_pipeline_record,
)


def _rows() -> list[dict[str, object]]:
    result = []
    for index in range(40):
        actual = float(index * index + 100)
        result.append(
            {
                "scenario_id": f"scenario-{index}",
                "family": "LEVELS" if index < 20 else "SHUTDOWN",
                "canonical_schedule_hash": f"hash-{index}",
                "actual_npv_rub": actual,
                "v2_npv_rub": actual + 10.0 - index % 3,
                "v3_npv_rub": actual + 4.0 - index % 2,
            }
        )
    return result


def test_blind_feature_cache_uses_frozen_direct_part_of_physical_blend() -> None:
    row = {"v3_npv_rub": 80.0, "v3_direct_npv_rub": 75.0}

    assert _locked_direct_candidate_npv(row, physical_npv_weight=0.2) == 75.0
    assert _locked_direct_candidate_npv(row, physical_npv_weight=0.0) == 80.0

    with pytest.raises(RuntimeError, match="lacks its frozen direct prediction"):
        _locked_direct_candidate_npv(
            {"v3_npv_rub": 80.0}, physical_npv_weight=0.2
        )


def test_family_stratified_bootstrap_is_deterministic_and_paired() -> None:
    rows = _rows()

    first = _bootstrap(rows, replicates=1_000)
    second = _bootstrap(rows, replicates=1_000)

    assert first == second
    improvement = first["mae_improvement_v2_minus_v3_rub"]
    assert improvement["ci95_low"] > 0.0
    assert improvement["probability_positive"] == 1.0
    assert first["family_counts"] == {"LEVELS": 20, "SHUTDOWN": 20}


def test_promotion_requires_mae_significance_and_rank_noninferiority() -> None:
    rows = _rows()
    actual = np.asarray([row["actual_npv_rub"] for row in rows])
    v2 = np.asarray([row["v2_npv_rub"] for row in rows])
    v3 = np.asarray([row["v3_npv_rub"] for row in rows])
    bootstrap = _bootstrap(rows, replicates=1_000)

    gates = _promotion_gates(
        _score(actual, v2),
        _score(actual, v3),
        bootstrap,
    )

    assert all(gates.values())
    bootstrap["mae_improvement_v2_minus_v3_rub"]["ci95_low"] = 0.0
    assert not _promotion_gates(_score(actual, v2), _score(actual, v3), bootstrap)[
        "mae_improvement_ci95_low_positive"
    ]


def test_score_is_stable_across_json_round_trip() -> None:
    actual = np.asarray([30.0, 20.0, 10.0])
    predicted = np.asarray([29.0, 18.0, 12.0])

    score = _score(actual, predicted)

    assert score == json.loads(json.dumps(score))
    assert set(score["ranking"]["precision_at_k"]) == {"1", "3"}


def test_blind2_promotion_requires_optimizer_top_five_safety() -> None:
    rows = _rows()
    actual = np.asarray([row["actual_npv_rub"] for row in rows])
    v2 = np.asarray([row["v2_npv_rub"] for row in rows])
    v3 = np.asarray([row["v3_npv_rub"] for row in rows])
    baseline = _score(actual, v2)
    candidate = _score(actual, v3)
    optimizer_gate = {
        "true_best_rank_max": 5,
        "precision_at_5_difference_min": -0.2,
    }

    gates = _promotion_gates(
        baseline,
        candidate,
        _bootstrap(rows, replicates=1_000),
        optimizer_ranking_gate=optimizer_gate,
    )

    assert gates["candidate_true_best_in_top5"]
    assert gates["candidate_precision_at5_noninferior"]
    candidate["rank_of_true_best"] = 6
    assert not _promotion_gates(
        baseline,
        candidate,
        _bootstrap(rows, replicates=1_000),
        optimizer_ranking_gate=optimizer_gate,
    )["candidate_true_best_in_top5"]


def test_unique_rows_rejects_inconsistent_duplicate_schedule() -> None:
    rows = _rows()
    duplicate = dict(rows[0])
    duplicate["scenario_id"] = "duplicate"
    rows.append(duplicate)

    assert len(_unique_rows(rows)) == 40

    rows[-1]["actual_npv_rub"] = float(rows[-1]["actual_npv_rub"]) + 1.0
    with pytest.raises(RuntimeError, match="different actual_npv_rub"):
        _unique_rows(rows)


def test_family_diagnostics_reports_small_family_without_fake_ranking() -> None:
    rows = _rows()
    rows[0]["family"] = "BASELINE"

    diagnostics = _family_diagnostics(rows)

    assert diagnostics["BASELINE"]["n"] == 1
    assert "v2_spearman" not in diagnostics["BASELINE"]
    assert diagnostics["SHUTDOWN"]["n"] == 20
    assert "v3_spearman" in diagnostics["SHUTDOWN"]


def test_protocol_pins_plan_bootstrap_and_checkpoint_bytes(tmp_path) -> None:
    baseline_path = tmp_path / "baseline.pt"
    candidate_path = tmp_path / "candidate.pt"
    baseline_path.write_bytes(b"baseline")
    candidate_path.write_bytes(b"candidate")
    protocol = {
        "format": "aios.surrogate-blind-promotion-protocol.v1",
        "frozen_before_first_successful_blind_response": True,
        "historical_test_allowed": False,
        "plan": {"plan_hash": "plan", "expected_scenarios": 81},
        "bootstrap": {"seed": 20260827, "replicates": 10_000},
        "promotion_gate": {
            "spearman_point_difference_min": -0.02,
            "spearman_ci95_difference_min": -0.03,
        },
        "baseline": {
            "model_version": "v2",
            "checkpoint_sha256": _sha256(baseline_path),
        },
        "candidate": {
            "model_version": "v3",
            "checkpoint_sha256": _sha256(candidate_path),
        },
    }

    _validate_protocol(
        protocol,
        baseline_path=baseline_path,
        baseline=SimpleNamespace(version="v2"),
        candidate_path=candidate_path,
        candidate=SimpleNamespace(version="v3"),
        blind={"plan_hash": "plan", "n_scenarios": 81},
        bootstrap_replicates=10_000,
    )

    corrected = SimpleNamespace(
        version="v3",
        target_provenance_hash="a" * 64,
        feature_context_sha256="c" * 64,
    )
    with pytest.raises(RuntimeError, match="target_provenance_hash"):
        _validate_protocol(
            protocol,
            baseline_path=baseline_path,
            baseline=SimpleNamespace(version="v2"),
            candidate_path=candidate_path,
            candidate=corrected,
            blind={"plan_hash": "plan", "n_scenarios": 81},
            bootstrap_replicates=10_000,
        )
    protocol["candidate"].update(
        {
            "target_provenance_hash": "a" * 64,
            "feature_context_sha256": "c" * 64,
        }
    )
    _validate_protocol(
        protocol,
        baseline_path=baseline_path,
        baseline=SimpleNamespace(version="v2"),
        candidate_path=candidate_path,
        candidate=corrected,
        blind={"plan_hash": "plan", "n_scenarios": 81},
        bootstrap_replicates=10_000,
    )

    candidate_path.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="checkpoint hash"):
        _validate_protocol(
            protocol,
            baseline_path=baseline_path,
            baseline=SimpleNamespace(version="v2"),
            candidate_path=candidate_path,
            candidate=SimpleNamespace(version="v3"),
            blind={"plan_hash": "plan", "n_scenarios": 81},
            bootstrap_replicates=10_000,
        )


def test_protocol_freezer_rejects_existing_response_and_pins_corrected_head(
    tmp_path,
) -> None:
    dataset = tmp_path / "blind"
    dataset.mkdir()
    checkpoint = tmp_path / "head.pt"
    checkpoint.write_bytes(b"head")
    head = SimpleNamespace(
        version="v4",
        target_provenance_hash="a" * 64,
        feature_provenance_hash="f" * 64,
        feature_context_sha256="c" * 64,
    )

    _assert_response_free(dataset)
    record = _head_record(checkpoint, head)
    assert record["model_version"] == "v4"
    assert record["target_provenance_hash"] == "a" * 64
    assert record["feature_context_sha256"] == "c" * 64

    (dataset / "cache").mkdir()
    (dataset / "cache" / "response.json").write_text("{}")
    with pytest.raises(RuntimeError, match="successful blind response"):
        _assert_response_free(dataset)


def test_blind_execution_requires_exact_frozen_plan_and_exclusion_audit(
    tmp_path,
) -> None:
    plan = tmp_path / "plan.json"
    audit = tmp_path / "plan_exclusion_audit.json"
    protocol = tmp_path / "protocol.json"
    plan.write_text("plan")
    audit.write_text("audit")
    protocol.write_text(
        json.dumps(
            {
                "format": "aios.surrogate-blind-promotion-protocol.v1",
                "frozen_before_first_successful_blind_response": True,
                "plan": {
                    "plan_hash": "p" * 64,
                    "expected_scenarios": 81,
                    "plan_sha256": _sha256(plan),
                    "exclusion_audit_sha256": _sha256(audit),
                },
            }
        )
    )

    _validate_execution_protocol(
        protocol, tmp_path, plan_hash="p" * 64, count=81
    )
    plan.write_text("tampered")
    with pytest.raises(RuntimeError, match="differs from frozen"):
        _validate_execution_protocol(
            protocol, tmp_path, plan_hash="p" * 64, count=81
        )


def test_blind2_execution_pins_physical_code_and_model_inputs(tmp_path) -> None:
    image = "openporousmedia/opmreleases@sha256:" + "d" * 64
    model = tmp_path / "model"
    model.mkdir()
    (model / "Model_Z.data").write_text("RUNSPEC\n", encoding="ascii")
    plan = tmp_path / "plan.json"
    audit = tmp_path / "plan_exclusion_audit.json"
    protocol = tmp_path / "protocol.json"
    plan.write_text("plan")
    audit.write_text("audit")
    protocol.write_text(
        json.dumps(
            {
                "format": "aios.surrogate-blind-promotion-protocol.v2",
                "frozen_before_first_successful_blind_response": True,
                "plan": {
                    "plan_hash": "p" * 64,
                    "expected_scenarios": 81,
                    "plan_sha256": _sha256(plan),
                    "exclusion_audit_sha256": _sha256(audit),
                },
                "physical_pipeline": physical_pipeline_record(
                    model, opm_image=image
                ),
            }
        )
    )

    _validate_execution_protocol(
        protocol,
        tmp_path,
        plan_hash="p" * 64,
        count=81,
        model_dir=model,
        opm_image=image,
    )
    (model / "Model_Z.data").write_text("RUNSPEC\n-- changed\n", encoding="ascii")
    with pytest.raises(RuntimeError, match="physical pipeline differs"):
        _validate_execution_protocol(
            protocol,
            tmp_path,
            plan_hash="p" * 64,
            count=81,
            model_dir=model,
            opm_image=image,
        )


def test_locked_predictions_require_complete_finite_unique_rows() -> None:
    locked = {
        "format": "aios.surrogate-locked-blind-predictions.v1",
        "response_data_read": False,
        "historical_test_read": False,
        "plan_hash": "plan",
        "protocol_sha256": "protocol",
        "baseline_version": "v2",
        "candidate_version": "v3",
        "n_scenarios": 2,
        "rows": [
            {
                "scenario_id": "a",
                "family": "BASELINE",
                "canonical_schedule_hash": "hash-a",
                "v2_npv_rub": 1.0,
                "v3_npv_rub": 2.0,
            },
            {
                "scenario_id": "b",
                "family": "LEVELS",
                "canonical_schedule_hash": "hash-b",
                "v2_npv_rub": 3.0,
                "v3_npv_rub": 4.0,
            },
        ],
    }
    kwargs = {
        "expected_scenarios": {
            "a": ("BASELINE", "hash-a"),
            "b": ("LEVELS", "hash-b"),
        },
        "plan_hash": "plan",
        "protocol_sha256": "protocol",
        "baseline_version": "v2",
        "candidate_version": "v3",
    }

    assert set(_validate_locked_predictions(locked, **kwargs)) == {"a", "b"}

    corrected = dict(locked)
    corrected["candidate_target_provenance_hash"] = "a" * 64
    corrected["candidate_feature_context_sha256"] = "c" * 64
    assert set(
        _validate_locked_predictions(
            corrected,
            **kwargs,
            candidate_target_provenance_hash="a" * 64,
            candidate_feature_context_sha256="c" * 64,
        )
    ) == {"a", "b"}
    corrected["candidate_target_provenance_hash"] = "b" * 64
    with pytest.raises(RuntimeError, match="target_provenance_hash"):
        _validate_locked_predictions(
            corrected,
            **kwargs,
            candidate_target_provenance_hash="a" * 64,
            candidate_feature_context_sha256="c" * 64,
        )

    blended = dict(locked)
    blended["baseline_physical_npv_sha256"] = "p" * 64
    blended["baseline_physical_npv_weight"] = 0.2
    blended["rows"] = [
        {
            **row,
            "v2_direct_npv_rub": row["v2_npv_rub"] - 0.5,
            "physical_npv_rub": row["v2_npv_rub"] + 2.0,
        }
        for row in locked["rows"]
    ]
    assert set(
        _validate_locked_predictions(
            blended,
            **kwargs,
            baseline_physical_npv_sha256="p" * 64,
            baseline_physical_npv_weight=0.2,
        )
    ) == {"a", "b"}
    del blended["rows"][0]["v2_direct_npv_rub"]
    with pytest.raises(RuntimeError, match="invalid locked v2_direct_npv_rub"):
        _validate_locked_predictions(
            blended,
            **kwargs,
            baseline_physical_npv_sha256="p" * 64,
            baseline_physical_npv_weight=0.2,
        )

    duplicate = dict(locked)
    duplicate["rows"] = [locked["rows"][0], locked["rows"][0]]
    with pytest.raises(RuntimeError, match="duplicate locked prediction"):
        _validate_locked_predictions(duplicate, **kwargs)

    nonfinite = dict(locked)
    nonfinite["rows"] = [dict(row) for row in locked["rows"]]
    nonfinite["rows"][1]["v3_npv_rub"] = float("nan")
    with pytest.raises(RuntimeError, match="invalid locked v3_npv_rub"):
        _validate_locked_predictions(nonfinite, **kwargs)


def test_deployment_decision_requires_exactly_all_frozen_gates() -> None:
    protocol = {
        "format": "aios.surrogate-blind-promotion-protocol.v1",
        "frozen_before_first_successful_blind_response": True,
        "historical_test_allowed": False,
        "plan": {"plan_hash": "plan", "expected_scenarios": 81},
        "bootstrap": {"seed": 7, "replicates": 10_000},
        "promotion_gate": {
            "spearman_point_difference_min": -0.02,
            "spearman_ci95_difference_min": -0.03,
        },
        "baseline": {"model_version": "v2"},
        "candidate": {"model_version": "v3"},
    }
    comparison = {
        "format": "aios.surrogate-blind-npv-comparison.v1",
        "historical_test_read": False,
        "blind_plan_hash": "plan",
        "blind_dataset_hash": "d" * 64,
        "raw_row_count": 81,
        "unique_schedule_count": 81,
        "baseline": {
            "version": "v2",
            "metrics": {
                "mae_rub": 10.0,
                "ranking": {"spearman_rank_correlation": 0.8},
            },
        },
        "candidate": {
            "version": "v3",
            "metrics": {
                "mae_rub": 8.0,
                "ranking": {"spearman_rank_correlation": 0.81},
            },
        },
        "bootstrap": {
            "seed": 7,
            "replicates": 10_000,
            "mae_improvement_v2_minus_v3_rub": {"ci95_low": 0.5},
            "spearman_difference_v3_minus_v2": {"ci95_low": -0.01},
        },
        "promotion_gates": {name: True for name in REQUIRED_GATES},
        "promote_candidate": True,
    }

    assert _validate_decision(comparison, protocol)

    comparison["candidate"]["metrics"]["mae_rub"] = 12.0
    comparison["promotion_gates"]["candidate_mae_lower"] = False
    comparison["promote_candidate"] = False
    assert not _validate_decision(comparison, protocol)

    comparison["promote_candidate"] = True
    with pytest.raises(RuntimeError, match="verdict is inconsistent"):
        _validate_decision(comparison, protocol)


def test_deployment_recomputes_metrics_from_blind_evidence() -> None:
    rows = _rows()
    for row in rows:
        row["response_hash"] = f"response-{row['scenario_id']}"
    unique = _unique_rows(rows)
    raw_actual, raw_v2, raw_v3 = (
        np.asarray([row[field] for row in rows])
        for field in ("actual_npv_rub", "v2_npv_rub", "v3_npv_rub")
    )
    actual, v2, v3 = (
        np.asarray([row[field] for row in unique])
        for field in ("actual_npv_rub", "v2_npv_rub", "v3_npv_rub")
    )
    bootstrap = _bootstrap(unique, replicates=1_000)
    v2_metrics = _score(actual, v2)
    v3_metrics = _score(actual, v3)
    gates = _promotion_gates(v2_metrics, v3_metrics, bootstrap)
    protocol = {
        "plan": {"plan_hash": "plan", "expected_scenarios": len(rows)},
        "bootstrap": {"seed": 20260827, "replicates": 1_000},
    }
    blind = {
        "format": "aios.surrogate-blind-dataset.v1",
        "n_scenarios": len(rows),
        "n_failed": 0,
        "n_skipped": 0,
        "plan_hash": "plan",
        "dataset_hash": "d" * 64,
        "scenario_identity": [
            {
                "scenario_id": row["scenario_id"],
                "family": row["family"],
                "canonical_schedule_hash": row["canonical_schedule_hash"],
                "response_hash": row["response_hash"],
            }
            for row in rows
        ],
    }
    locked = {
        "format": "aios.surrogate-locked-blind-predictions.v1",
        "response_data_read": False,
        "historical_test_read": False,
        "plan_hash": "plan",
        "protocol_sha256": "protocol",
        "baseline_version": "v2",
        "candidate_version": "v3",
        "n_scenarios": len(rows),
        "rows": [
            {
                "scenario_id": row["scenario_id"],
                "family": row["family"],
                "canonical_schedule_hash": row["canonical_schedule_hash"],
                "v2_npv_rub": row["v2_npv_rub"],
                "v3_npv_rub": row["v3_npv_rub"],
            }
            for row in rows
        ],
    }
    comparison = {
        "protocol_sha256": "protocol",
        "blind_dataset_hash": blind["dataset_hash"],
        "primary_population": "unique canonical_schedule_hash",
        "raw_row_count": len(rows),
        "unique_schedule_count": len(unique),
        "duplicate_row_count": 0,
        "baseline": {"version": "v2", "metrics": v2_metrics},
        "candidate": {"version": "v3", "metrics": v3_metrics},
        "raw_metrics": {
            "baseline": _score(raw_actual, raw_v2),
            "candidate": _score(raw_actual, raw_v3),
        },
        "family_diagnostics_unique": _family_diagnostics(unique),
        "bootstrap": bootstrap,
        "promotion_gates": gates,
        "rows": rows,
    }

    _validate_evidence(comparison, blind, locked, protocol)

    excluded_id = rows[0]["scenario_id"]
    primary = _unique_rows(rows[1:])
    primary_actual, primary_v2, primary_v3 = (
        np.asarray([row[field] for row in primary])
        for field in ("actual_npv_rub", "v2_npv_rub", "v3_npv_rub")
    )
    primary_bootstrap = _bootstrap(primary, replicates=1_000)
    primary_v2_metrics = _score(primary_actual, primary_v2)
    primary_v3_metrics = _score(primary_actual, primary_v3)
    protocol["plan"]["primary_excluded_scenario_ids"] = [excluded_id]
    protocol["primary_population"] = (
        "unique non-overlapping canonical_schedule_hash"
    )
    comparison.update(
        {
            "primary_population": protocol["primary_population"],
            "primary_excluded_scenario_ids": [excluded_id],
            "unique_schedule_count": len(primary),
            "duplicate_row_count": 0,
            "baseline": {"version": "v2", "metrics": primary_v2_metrics},
            "candidate": {"version": "v3", "metrics": primary_v3_metrics},
            "family_diagnostics_unique": _family_diagnostics(primary),
            "bootstrap": primary_bootstrap,
            "promotion_gates": _promotion_gates(
                primary_v2_metrics, primary_v3_metrics, primary_bootstrap
            ),
        }
    )
    _validate_evidence(comparison, blind, locked, protocol)

    comparison["candidate"]["metrics"]["mae_rub"] += 1.0
    with pytest.raises(RuntimeError, match="v3 metrics"):
        _validate_evidence(comparison, blind, locked, protocol)


def test_economics_lock_pins_sources_schedule_and_normatives(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "tools.surrogate_evaluate_blind_npv.methodology_version_hash",
        lambda: "methodology",
    )
    project = tmp_path / "project"
    source_hashes = {}
    for relative in ECONOMICS_LOCK_SOURCES:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
        source_hashes[relative] = _sha256(path)
    schedule = tmp_path / "schedule.inc"
    normatives = tmp_path / "normatives.xlsx"
    schedule.write_bytes(b"schedule")
    normatives.write_bytes(b"normatives")
    lock = {
        "format": "aios.surrogate-blind-economics-lock.v1",
        "historical_test_read": False,
        "response_data_read": False,
        "plan_hash": "plan",
        "source_sha256": source_hashes,
        "methodology_version_hash": "methodology",
        "model_schedule_sha256": _sha256(schedule),
        "normatives_sha256": _sha256(normatives),
    }

    _validate_economics_lock(
        lock,
        project_root=project,
        model_schedule=schedule,
        normatives=normatives,
        plan_hash="plan",
    )

    (project / "economics/fund.py").write_text("changed")
    with pytest.raises(RuntimeError, match="economics/fund.py"):
        _validate_economics_lock(
            lock,
            project_root=project,
            model_schedule=schedule,
            normatives=normatives,
            plan_hash="plan",
        )


def test_final_audit_pins_blind_report_bytes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "tools.surrogate_finalize_blind_report.load_direct_npv_head",
        lambda _path: SimpleNamespace(version="v2", target_provenance_hash=""),
    )
    blind = {
        "n_scenarios": 81,
        "n_failed": 0,
        "n_skipped": 0,
        "plan_hash": "plan",
        "scenario_identity": [{} for _ in range(81)],
    }
    comparison = {
        "blind_plan_hash": "plan",
        "blind_report_sha256": "blind-hash",
        "protocol_sha256": "protocol-hash",
        "economics_lock_sha256": "economics-hash",
        "historical_test_read": False,
        "raw_row_count": 81,
        "unique_schedule_count": 81,
        "promote_candidate": False,
        "promotion_gates": {"gate": False},
    }
    decision = {
        "promoted": False,
        "comparison_sha256": "comparison-hash",
        "blind_report_sha256": "blind-hash",
        "protocol_sha256": "protocol-hash",
        "economics_lock_sha256": "economics-hash",
        "promotion_gates": {"gate": False},
        "production_manifest_sha256_before": "manifest-hash",
    }
    protocol = {
        "plan": {"expected_scenarios": 81, "plan_hash": "plan"},
        "baseline": {"model_version": "v2"},
        "candidate": {"model_version": "v3"},
    }
    production = {
        "npv_head": "head.pt",
        "active_economic_model_version": "v2",
    }

    checks = _verify(
        blind,
        comparison,
        decision,
        protocol,
        production,
        blind_report_sha256="blind-hash",
        comparison_sha256="comparison-hash",
        protocol_sha256="protocol-hash",
        economics_lock_sha256="economics-hash",
        production_manifest_sha256="manifest-hash",
        manifest_root=tmp_path,
    )

    assert all(checks.values())
    checks = _verify(
        blind,
        comparison,
        decision,
        protocol,
        production,
        blind_report_sha256="tampered",
        comparison_sha256="comparison-hash",
        protocol_sha256="protocol-hash",
        economics_lock_sha256="economics-hash",
        production_manifest_sha256="manifest-hash",
        manifest_root=tmp_path,
    )
    assert checks["blind_report_hash_matches"] is False
