from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import torch
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import Ridge

from surrogate.npv_block_head import (
    LEGACY_IMPLEMENTATION_HASHES,
    block_implementation_hash,
)
from surrogate.npv_head import feature_implementation_hash
from surrogate.npv_target import (
    TARGET_PROVENANCE_FORMAT,
    TARGET_SOURCE_FILES,
    validate_target_provenance,
)
from tools.surrogate_benchmark_npv_models import (
    BLOCK_SHORTLIST_PROVENANCE,
    FEATURE_WIDTHS,
    SELECTION_RULE,
    _apply_calibration,
    _deployable_spec,
    _factories,
    _linear_calibration,
    _load_selection_data,
    _nested_selection_policy,
    _resume_candidates,
    _unique_schedule_population,
    _validate_selection_labels,
    _winner,
    screen_implementation_hash,
    screen_runtime_versions,
)
from tools.surrogate_build_disclosed_blind_npv_labels import (
    _validate_disclosed_rows,
    _validate_disclosure,
)
from tools.surrogate_build_npv_labels import (
    _selected_identities,
    _target_provenance,
    _validate_label_rows,
)
from tools.surrogate_fit_locked_npv_candidate import (
    _load_augmentation,
    _locked_calibration,
    _locked_winner,
    _parser as _fit_parser,
    _refit_population_calibration,
    _validate_locked_inputs,
)


def _split_report() -> dict:
    def rows(bucket: str, count: int) -> list[dict]:
        return [
            {
                "source_dataset": "historical",
                "scenario_id": f"{bucket}-{index}",
                "canonical_schedule_hash": f"{bucket}-{index}",
            }
            for index in range(count)
        ]

    return {
        "split_identity": {
            "train": rows("train", 490),
            "validation": rows("validation", 105),
            "test": rows("test", 105),
        }
    }


def test_label_population_requires_explicit_unique_buckets() -> None:
    selected = _selected_identities(_split_report(), ("train", "validation"))

    assert len(selected) == 595
    assert {bucket for bucket, _ in selected} == {"train", "validation"}
    assert all(bucket != "test" for bucket, _ in selected)
    with pytest.raises(ValueError, match="non-empty unique"):
        _selected_identities(_split_report(), ("train", "train"))


def test_resumed_label_rows_are_identity_and_value_checked() -> None:
    expected = _selected_identities(_split_report(), ("train", "validation"))
    bucket, identity = expected[0]
    key = f"{identity['source_dataset']}:{identity['scenario_id']}"
    payload = {
        "rows": {
            key: {
                **identity,
                "bucket": bucket,
                "response_hash": "a" * 64,
                "npv_rub": 123.0,
            }
        }
    }

    _validate_label_rows(payload, expected)
    payload["rows"][key]["canonical_schedule_hash"] = "tampered"
    with pytest.raises(RuntimeError, match="identity differs"):
        _validate_label_rows(payload, expected)
    payload["rows"][key]["canonical_schedule_hash"] = identity[
        "canonical_schedule_hash"
    ]
    payload["rows"][key]["npv_rub"] = float("nan")
    with pytest.raises(RuntimeError, match="NPV is invalid"):
        _validate_label_rows(payload, expected)


def test_target_provenance_pins_code_schedule_and_normatives(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    for relative in TARGET_SOURCE_FILES:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    schedule = tmp_path / "schedule.inc"
    normatives = tmp_path / "normatives.xlsx"
    schedule.write_bytes(b"schedule")
    normatives.write_bytes(b"normatives")
    monkeypatch.setattr(
        "tools.surrogate_build_npv_labels.methodology_version_hash",
        lambda: "a" * 64,
    )

    provenance = _target_provenance(
        project_root=project,
        model_schedule=schedule,
        normatives=normatives,
    )

    assert provenance["methodology_version_hash"] == "a" * 64
    assert (
        provenance["model_schedule_sha256"] == hashlib.sha256(b"schedule").hexdigest()
    )
    assert provenance["normatives_sha256"] == hashlib.sha256(b"normatives").hexdigest()
    assert len(provenance["target_provenance_sha256"]) == 64
    assert set(provenance["source_sha256"]) == set(TARGET_SOURCE_FILES)
    assert (
        validate_target_provenance(provenance) == provenance["target_provenance_sha256"]
    )


def test_selection_rejects_any_label_artifact_that_read_test(tmp_path) -> None:
    project = tmp_path / "project"
    for relative in TARGET_SOURCE_FILES:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    schedule = tmp_path / "schedule.inc"
    normatives = tmp_path / "normatives.xlsx"
    schedule.write_bytes(b"schedule")
    normatives.write_bytes(b"normatives")
    provenance = _target_provenance(
        project_root=project,
        model_schedule=schedule,
        normatives=normatives,
    )
    labels = {
        "format": "aios.surrogate-npv-labels.v1",
        "historical_test_read": False,
        "included_buckets": ["train", "validation"],
        "expected_rows": 595,
        "target_provenance": provenance,
        "rows": {
            f"row-{index}": {"bucket": "train" if index < 490 else "validation"}
            for index in range(595)
        },
    }

    _validate_selection_labels(labels)
    labels["historical_test_read"] = True
    with pytest.raises(RuntimeError, match=r"train\+validation-only"):
        _validate_selection_labels(labels)


def test_selection_rejects_incomplete_or_tampered_target_sources(tmp_path) -> None:
    project = tmp_path / "project"
    for relative in TARGET_SOURCE_FILES:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    schedule = tmp_path / "schedule.inc"
    normatives = tmp_path / "normatives.xlsx"
    schedule.write_bytes(b"schedule")
    normatives.write_bytes(b"normatives")
    provenance = _target_provenance(
        project_root=project,
        model_schedule=schedule,
        normatives=normatives,
    )

    assert provenance["format"] == TARGET_PROVENANCE_FORMAT
    provenance["source_sha256"].pop("economics/fund.py")
    with pytest.raises(RuntimeError, match="source population"):
        validate_target_provenance(provenance)


def test_nested_selection_policy_is_complete_and_deterministic() -> None:
    rng = np.random.default_rng(42)
    matrix = np.zeros((120, 84))
    matrix[:, :2] = rng.normal(size=(120, 2))
    target = 5.0 * matrix[:, 0] - 2.0 * matrix[:, 1] + rng.normal(scale=0.05, size=120)
    groups = np.repeat(np.arange(60), 2)
    factories = {
        "krr-poly2-global-a0.1": lambda: Ridge(alpha=0.1),
        "krr-poly2-global-a1": lambda: DummyRegressor(strategy="mean"),
    }

    first = _nested_selection_policy(
        factories,
        matrix,
        target,
        groups,
        outer_folds=3,
        outer_repeats=2,
        seed=17,
    )
    second = _nested_selection_policy(
        factories,
        matrix,
        target,
        groups,
        outer_folds=3,
        outer_repeats=2,
        seed=17,
    )

    assert first == second
    assert len(first["folds"]) == 6
    assert sum(first["winner_counts"].values()) == 6
    assert first["mean_repeat_mae_rub"] < 0.1
    assert first["averaged_oof"]["ranking"]["spearman_rank_correlation"] > 0.99


def test_nested_selection_policy_resumes_exact_fold_prefix() -> None:
    rng = np.random.default_rng(43)
    matrix = np.zeros((60, 84))
    matrix[:, :2] = rng.normal(size=(60, 2))
    target = 3.0 * matrix[:, 0] + matrix[:, 1]
    groups = np.repeat(np.arange(30), 2)
    factories = {
        "krr-poly2-global-a0.1": lambda: Ridge(alpha=0.1),
        "krr-poly2-global-a1": lambda: DummyRegressor(strategy="mean"),
    }
    saved = None

    class StopAfterTwo(RuntimeError):
        pass

    def checkpoint(progress) -> None:
        nonlocal saved
        saved = json.loads(json.dumps(progress))
        if progress["completed_folds"] == 2:
            raise StopAfterTwo

    with pytest.raises(StopAfterTwo):
        _nested_selection_policy(
            factories,
            matrix,
            target,
            groups,
            outer_folds=3,
            outer_repeats=2,
            seed=19,
            progress_callback=checkpoint,
        )
    assert saved is not None
    resumed = _nested_selection_policy(
        factories,
        matrix,
        target,
        groups,
        outer_folds=3,
        outer_repeats=2,
        seed=19,
        resume=saved,
    )
    uninterrupted = _nested_selection_policy(
        factories,
        matrix,
        target,
        groups,
        outer_folds=3,
        outer_repeats=2,
        seed=19,
    )

    assert resumed == uninterrupted


def test_selection_can_load_safe_cache_without_monolithic_tensors(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    for relative in TARGET_SOURCE_FILES:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    schedule = tmp_path / "schedule.inc"
    normatives = tmp_path / "normatives.xlsx"
    schedule.write_bytes(b"schedule")
    normatives.write_bytes(b"normatives")
    provenance = _target_provenance(
        project_root=project,
        model_schedule=schedule,
        normatives=normatives,
    )
    identities = []
    rows = {}
    for index in range(595):
        bucket = "train" if index < 490 else "validation"
        schedule_hash = f"{index:064x}"
        identity = {
            "bucket": bucket,
            "source_dataset": "historical",
            "scenario_id": f"scenario-{index}",
            "canonical_schedule_hash": schedule_hash,
        }
        identities.append(identity)
        rows[f"historical:scenario-{index}"] = {
            **identity,
            "response_hash": f"{10_000 + index:064x}",
            "npv_rub": float(index),
        }
    dataset_hash = "d" * 64
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(
        json.dumps(
            {
                "format": "aios.surrogate-npv-labels.v1",
                "historical_test_read": False,
                "included_buckets": ["train", "validation"],
                "expected_rows": 595,
                "dataset_hash": dataset_hash,
                "target_provenance": provenance,
                "rows": rows,
            }
        )
    )
    cache_path = tmp_path / "features.pt"
    torch.save(
        {
            "format": "aios.npv-selection-features.v2",
            "response_data_read": False,
            "historical_test_read": False,
            "dataset_hash": dataset_hash,
            "feature_set": "economic",
            "feature_width": 2,
            "feature_provenance_hash": feature_implementation_hash(),
            "feature_context_sha256": "c" * 64,
            "identities": identities,
            "features": torch.arange(1190, dtype=torch.float32).reshape(595, 2),
        },
        cache_path,
    )
    monkeypatch.setitem(FEATURE_WIDTHS, "economic", 2)

    matrix, target, groups, loaded_identities, loaded_hash = _load_selection_data(
        None, labels_path, cache_path
    )

    assert matrix.shape == (595, 2)
    assert target[-1] == 594.0
    assert len(set(groups)) == 595
    assert loaded_identities == identities
    assert loaded_hash == dataset_hash


def test_selection_deduplicates_only_identical_schedule_evidence() -> None:
    matrix = np.asarray([[1.0, 2.0], [1.0, 2.0], [3.0, 4.0]])
    target = np.asarray([10.0, 10.0, 20.0])
    identities = [
        {"canonical_schedule_hash": "a", "scenario_id": "first"},
        {"canonical_schedule_hash": "a", "scenario_id": "duplicate"},
        {"canonical_schedule_hash": "b", "scenario_id": "other"},
    ]

    unique_x, unique_y, unique_identities = _unique_schedule_population(
        matrix, target, identities, ["r1", "r1", "r2"]
    )

    assert unique_x.tolist() == [[1.0, 2.0], [3.0, 4.0]]
    assert unique_y.tolist() == [10.0, 20.0]
    assert [item["scenario_id"] for item in unique_identities] == ["first", "other"]
    target[1] = 11.0
    with pytest.raises(RuntimeError, match="inconsistent evidence"):
        _unique_schedule_population(
            matrix, target, identities, ["r1", "r1", "r2"]
        )


def test_model_selection_prefers_top_five_regret_inside_spearman_band() -> None:
    def item(candidate_id: str, *, rho: float, regret: float, mae: float) -> dict:
        return {
            "candidate_id": candidate_id,
            "oof": {
                "mae_rub": mae,
                "rank_of_true_best": 1 if regret == 0.0 else 9,
                "ranking": {
                    "spearman_rank_correlation": rho,
                    "precision_at_k": {5: 0.4},
                    "regret_at_k_rub": {5: regret},
                },
            },
        }

    calibrated_but_misses_best = item(
        "low-mae", rho=0.80, regret=30_000_000.0, mae=5_000_000.0
    )
    optimizer_safe = item("zero-regret", rho=0.79, regret=0.0, mae=8_000_000.0)

    assert _winner([calibrated_but_misses_best, optimizer_safe]) is optimizer_safe

    serialized = json.loads(json.dumps([calibrated_but_misses_best, optimizer_safe]))
    assert _winner(serialized)["candidate_id"] == "zero-regret"


def test_incomplete_screen_resumes_only_exact_candidate_prefix(tmp_path) -> None:
    candidate = {
        "candidate_id": "first",
        "oof": {
            "mae_rub": 1.0,
            "rank_of_true_best": 1,
            "ranking": {
                "spearman_rank_correlation": 0.9,
                "precision_at_k": {"5": 1.0},
                "regret_at_k_rub": {"5": 0.0},
            },
        },
    }
    contract = {"seed": 17, "input_artifacts": {"labels": {"sha256": "a"}}}
    report = {
        "format": "aios.surrogate-npv-model-screen.v2",
        "status": "incomplete",
        **contract,
        "candidate_count": 2,
        "completed_candidates": 1,
        "winner_so_far": candidate,
        "candidates": [candidate],
        "seconds": 12.5,
    }
    path = tmp_path / "screen.json"
    path.write_text(json.dumps(report))

    candidates, loaded, elapsed = _resume_candidates(
        path, contract=contract, candidate_ids=["first", "second"]
    )

    assert candidates == [candidate]
    assert loaded == report
    assert elapsed == 12.5
    with pytest.raises(RuntimeError, match="resume contract differs"):
        _resume_candidates(
            path,
            contract={**contract, "seed": 18},
            candidate_ids=["first", "second"],
        )
    report["status"] = "complete"
    path.write_text(json.dumps(report))
    with pytest.raises(FileExistsError, match="complete screen"):
        _resume_candidates(
            path, contract=contract, candidate_ids=["first", "second"]
        )


def test_grouped_oof_calibration_restores_shrunken_npv_scale() -> None:
    actual = np.linspace(-300.0, 500.0, 101)
    predicted = 100.0 + 0.4 * actual

    calibration = _linear_calibration(actual, predicted)
    restored = _apply_calibration(predicted, calibration)

    assert calibration["slope"] == pytest.approx(2.5)
    assert calibration["intercept_rub"] == pytest.approx(-250.0)
    assert restored == pytest.approx(actual)
    assert _linear_calibration(actual, actual)["method"] == "identity_no_mae_gain"

    biased = actual - 37.0
    bias_only = _linear_calibration(actual, biased)
    assert bias_only["method"] == "grouped_oof_median_bias_v1"
    assert bias_only["slope"] == 1.0
    assert bias_only["intercept_rub"] == pytest.approx(37.0)


def test_augmented_fit_refits_only_calibration_with_frozen_candidate() -> None:
    rng = np.random.default_rng(91)
    matrix = rng.normal(size=(60, 84))
    target = 2.0e8 * matrix[:, 0] - 0.7e8 * matrix[:, 1]
    groups = np.repeat(np.arange(30), 2).astype(str)
    screen = {
        "folds": 3,
        "seed": 17,
        "trees": 8,
        "deployable_calibration": {"oof_repeats": 2},
    }

    calibration = _refit_population_calibration(
        screen,
        "krr-poly2-global-a0.3",
        matrix,
        target,
        groups,
    )

    assert calibration["protocol"] == "frozen_candidate_repeated_grouped_oof_v1"
    assert calibration["fit_population_rows"] == 60
    assert calibration["candidate_id"] == "krr-poly2-global-a0.3"
    assert calibration["calibrated_oof"]["mae_rub"] <= calibration[
        "raw_averaged_oof"
    ]["mae_rub"]


def _complete_screen(selected_id: str) -> dict:
    candidate_ids = list(_factories(seed=17, trees=8))
    candidates = []
    for candidate_id in candidate_ids:
        selected = candidate_id == selected_id
        item = {
            "candidate_id": candidate_id,
            "oof": {
                "mae_rub": 1.0 if selected else 10.0,
                "rank_of_true_best": 1 if selected else 10,
                "ranking": {
                    "spearman_rank_correlation": 0.9 if selected else 0.5,
                    "precision_at_k": {"5": 1.0 if selected else 0.0},
                    "regret_at_k_rub": {"5": 0.0 if selected else 10.0},
                },
            },
        }
        spec = _deployable_spec(candidate_id)
        if spec is not None:
            item["deployable_spec"] = spec
        candidates.append(item)
    selected_item = next(
        item for item in candidates if item["candidate_id"] == selected_id
    )
    deployable_ids = [
        item["candidate_id"]
        for item in candidates
        if _deployable_spec(item["candidate_id"]) is not None
    ]
    screen = {
        "format": "aios.surrogate-npv-model-screen.v2",
        "status": "complete",
        "seed": 17,
        "trees": 8,
        "folds": 3,
        "outer_folds": 3,
        "outer_repeats": 2,
        "candidate_count": len(candidates),
        "completed_candidates": len(candidates),
        "candidates": candidates,
        "winner": selected_item,
        "selection_rule": SELECTION_RULE,
        "block_shortlist_provenance": BLOCK_SHORTLIST_PROVENANCE,
        "screen_implementation_sha256": screen_implementation_hash(),
        "block_implementation_sha256": block_implementation_hash(),
        "runtime_versions": screen_runtime_versions(),
        "deployable_winner": selected_item,
        "nested_deployable_selection": {
            "protocol": "repeated_nested_group_cv_v2",
            "selection_candidates": deployable_ids,
            "selection_rule": SELECTION_RULE,
            "inner_folds": 3,
            "outer_folds": 3,
            "outer_repeats": 2,
            "seed": 17,
            "winner_counts": {selected_id: 6},
            "folds": [
                {"fold": index, "selected_candidate_id": selected_id}
                for index in range(6)
            ],
            "repeat_metrics": [{}, {}],
            "averaged_oof": {},
        },
        "deployable_calibration": {
            "candidate_id": selected_id,
            "method": "grouped_oof_ols_v1",
            "slope": 1.2,
            "intercept_rub": -5.0,
            "oof_repeats": 3,
            "raw_averaged_oof": {},
            "calibrated_oof": {},
        },
    }
    return screen


def test_locked_fit_can_only_use_finalized_deployable_winner() -> None:
    screen = _complete_screen("krr-poly2-temporal-a0.3")
    selected = screen["deployable_winner"]

    winner, frozen = _locked_winner(screen, None)

    assert winner["feature_set"] == "temporal"
    assert winner["ridge"] == pytest.approx(0.3)
    assert frozen is selected
    assert _locked_calibration(screen, selected["candidate_id"]) == (1.2, -5.0)
    with pytest.raises(RuntimeError, match="differs from frozen"):
        _locked_winner(screen, "krr-poly2-global-a0.1")
    screen["status"] = "incomplete"
    with pytest.raises(RuntimeError, match="finalized"):
        _locked_winner(screen, None)

    block_id = "block-joint-s0-a0.3"
    screen = _complete_screen(block_id)
    block_winner, _ = _locked_winner(screen, None)
    assert block_winner["model_type"] == "block_poly2"
    assert block_winner["weights"] == [0.0, 0.7, 0.3, 0.0]

    screen["block_implementation_sha256"] = next(
        iter(LEGACY_IMPLEMENTATION_HASHES)
    )
    legacy_winner, _ = _locked_winner(screen, None)
    assert legacy_winner == block_winner
    screen["block_implementation_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="block runtime differs"):
        _locked_winner(screen, None)
    screen["block_implementation_sha256"] = block_implementation_hash()

    screen["deployable_winner"] = screen["candidates"][0]
    with pytest.raises(RuntimeError, match="deployable winner is inconsistent"):
        _locked_winner(screen, None)


def test_locked_fit_rejects_training_artifact_changed_after_screen(tmp_path) -> None:
    paths = {
        name: tmp_path / f"{name}.bin"
        for name in ("tensors", "labels", "feature_cache")
    }
    for name, path in paths.items():
        path.write_bytes(name.encode())
    screen = {
        "input_artifacts": {
            name: {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in paths.items()
        }
    }

    _validate_locked_inputs(screen, **paths)
    screen["input_artifacts"].pop("tensors")
    _validate_locked_inputs(
        screen,
        tensors=None,
        labels=paths["labels"],
        feature_cache=paths["feature_cache"],
    )
    paths["labels"].write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="labels differs"):
        _validate_locked_inputs(
            screen,
            tensors=None,
            labels=paths["labels"],
            feature_cache=paths["feature_cache"],
        )


def test_disclosed_blind_labels_require_complete_final_hash_chain() -> None:
    identities = [{"scenario_id": f"blind-{index}"} for index in range(81)]
    blind = {
        "format": "aios.surrogate-blind-dataset.v1",
        "n_scenarios": 81,
        "n_failed": 0,
        "n_skipped": 0,
        "scenario_identity": identities,
    }
    comparison = {
        "format": "aios.surrogate-blind-npv-comparison.v1",
        "blind_report_sha256": "b" * 64,
        "raw_row_count": 81,
    }
    final_audit = {
        "format": "aios.surrogate-blind-final-audit.v1",
        "all_checks_pass": True,
        "blind_report_sha256": "b" * 64,
        "comparison_sha256": "c" * 64,
        "decision_sha256": "d" * 64,
    }

    _validate_disclosure(
        blind,
        comparison,
        final_audit,
        blind_sha256="b" * 64,
        comparison_sha256="c" * 64,
        decision_sha256="d" * 64,
    )
    final_audit["all_checks_pass"] = False
    with pytest.raises(RuntimeError, match="final disclosure"):
        _validate_disclosure(
            blind,
            comparison,
            final_audit,
            blind_sha256="b" * 64,
            comparison_sha256="c" * 64,
            decision_sha256="d" * 64,
        )


def test_resumed_disclosed_rows_pin_response_identity_and_npv() -> None:
    identities = {
        "blind-1": {
            "scenario_id": "blind-1",
            "family": "LEVELS",
            "canonical_schedule_hash": "s" * 64,
            "response_hash": "r" * 64,
        }
    }
    comparison = {"blind-1": {"response_hash": "r" * 64}}
    rows = {
        "blind-1": {
            **identities["blind-1"],
            "npv_rub": 42.0,
        }
    }

    _validate_disclosed_rows(rows, identities, comparison, require_complete=True)
    rows["blind-1"]["response_hash"] = "x" * 64
    with pytest.raises(RuntimeError, match="identity differs"):
        _validate_disclosed_rows(rows, identities, comparison, require_complete=True)


def test_locked_fit_accepts_disclosed_blind_only_as_frozen_augmentation(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    for relative in TARGET_SOURCE_FILES:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    schedule = tmp_path / "schedule.inc"
    normatives = tmp_path / "normatives.xlsx"
    schedule.write_bytes(b"schedule")
    normatives.write_bytes(b"normatives")
    provenance = _target_provenance(
        project_root=project,
        model_schedule=schedule,
        normatives=normatives,
    )
    target_hash = provenance["target_provenance_sha256"]
    context_hash = "c" * 64
    identities = [
        {
            "scenario_id": f"blind-{index}",
            "family": "LEVELS",
            "canonical_schedule_hash": f"{1000 + index:064x}",
        }
        for index in range(81)
    ]
    features_path = tmp_path / "blind_features.pt"
    torch.save(
        {
            "format": "aios.surrogate-blind-npv-features.v2",
            "response_data_read": False,
            "historical_test_read": False,
            "feature_set": "economic",
            "feature_provenance_hash": feature_implementation_hash(),
            "feature_context_sha256": context_hash,
            "plan_hash": "p" * 64,
            "identities": identities,
            "features": torch.ones(81, 2),
        },
        features_path,
    )
    labels_path = tmp_path / "blind_labels.json"
    labels_path.write_text(
        json.dumps(
            {
                "format": "aios.surrogate-disclosed-blind-npv-labels.v1",
                "historical_test_read": False,
                "blind_response_read_after_final_audit": True,
                "fit_population_role": (
                    "augmentation_after_frozen_hyperparameter_selection"
                ),
                "expected_rows": 81,
                "plan_hash": "p" * 64,
                "target_provenance": provenance,
                "rows": {
                    item["scenario_id"]: {**item, "npv_rub": float(index)}
                    for index, item in enumerate(identities)
                },
            }
        )
    )

    matrix, target, loaded, population_hash, excluded = _load_augmentation(
        features_path,
        labels_path,
        target_provenance_hash=target_hash,
        feature_context_sha256=context_hash,
        feature_width=2,
        historical_schedule_hashes=set(),
    )

    assert matrix.shape == (81, 2)
    assert target[-1] == 80.0
    assert loaded == identities
    assert excluded == []
    assert len(population_hash) == 64
    matrix, target, loaded, _, excluded = _load_augmentation(
        features_path,
        labels_path,
        target_provenance_hash=target_hash,
        feature_context_sha256=context_hash,
        feature_width=2,
        historical_schedule_hashes={identities[0]["canonical_schedule_hash"]},
    )
    assert matrix.shape == (80, 2)
    assert target[0] == 1.0
    assert loaded == identities[1:]
    assert excluded == [
        {
            "scenario_id": "blind-0",
            "canonical_schedule_hash": identities[0]["canonical_schedule_hash"],
            "reason": "historical_schedule_overlap",
        }
    ]


def test_locked_fit_parser_pairs_multiple_disclosed_augmentations() -> None:
    args = _fit_parser().parse_args(
        [
            "--labels",
            "historical.json",
            "--feature-cache",
            "historical.pt",
            "--screen-report",
            "screen.json",
            "--output-dir",
            "locked",
            "--augmentation-features",
            "blind1.pt",
            "--augmentation-labels",
            "blind1.json",
            "--augmentation-features",
            "blind2.pt",
            "--augmentation-labels",
            "blind2.json",
        ]
    )

    assert args.augmentation_features == [Path("blind1.pt"), Path("blind2.pt")]
    assert args.augmentation_labels == [
        Path("blind1.json"),
        Path("blind2.json"),
    ]
