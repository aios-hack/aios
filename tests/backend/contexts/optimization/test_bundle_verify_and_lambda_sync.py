from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from backend.contexts.optimization.infrastructure.artifacts import (
    RuntimeArtifactError,
    verify_bundle,
)
from backend.contexts.optimization.application.environment import (
    LambdaDesyncError,
    _lambda_strict_enabled,
    lambda_sync_provenance,
    npv_blend_provenance,
)
from backend.contexts.optimization.domain.errors import ScheduleSearchError
from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.shared.paths import data_root
from backend.contexts.connectivity.domain.measure import load_lambda
from backend.contexts.surrogate.domain.features import FeatureContext, HistoryTargets
from backend.contexts.surrogate.infrastructure.model_z_context import ModelZFeatureArtifact
from backend.interfaces.cli.surrogate import release as surrogate_release


def _lambda(seed: float) -> Lambda:
    return Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2025, 9, 1),
        producers=("P1",),
        injectors=("I1",),
        matrix=((seed,),),
        lag_months=0,
        amplitude=1.0,
        stability=0.5,
        rank=1,
        condition_number=2.0,
        achievability_ok={"I1": True},
    )


def _context(influence: Lambda | None) -> ModelZFeatureArtifact:
    return ModelZFeatureArtifact(
        context=FeatureContext(
            control_dates=(date(2007, 1, 1),),
            history_start=date(2000, 1, 1),
            history_prefix_hash="a" * 64,
            history_targets={
                "P1": HistoryTargets(
                    target_liquid_m3=1.0, target_injection_m3=0.0, event_count=1
                )
            },
            static_features={"P1": {"head_i": 1.0}},
            lambda_windows=() if influence is None else (influence,),
        ),
        dataset_hash="d" * 64,
        lambda_source_hash="s" * 64,
        n_training_scenarios=490,
    )


class _Head:
    version = "v" * 64
    physical_npv_weight = 0.2
    physical_ensemble_version = "e" * 64
    physical_blend_provenance_hash = "b" * 64


def _bundle(root: Path, contents: dict[str, bytes]) -> Path:
    for name, payload in contents.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (root / "release.json").write_text(
        json.dumps(
            {
                "format": "aios.surrogate-release.v1",
                "files_sha256": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in contents.items()
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def test_intact_bundle_verifies_clean(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path / "bundle",
        {"weights/model.pt": b"weights", "feature_context.json": b"{}"},
    )

    verdict = verify_bundle(root)

    assert verdict.ok
    assert verdict.exit_code == 0
    assert verdict.mismatched == ()
    assert verdict.extra_files == ()
    assert len(verdict.files) == 2


def test_corrupted_file_is_detected_with_nonzero_exit(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path / "bundle",
        {"weights/model.pt": b"weights", "feature_context.json": b"{}"},
    )
    (root / "weights/model.pt").write_bytes(b"weights-tampered")

    verdict = verify_bundle(root)

    assert not verdict.ok
    assert verdict.exit_code == 1
    assert [item.path for item in verdict.mismatched] == ["weights/model.pt"]
    assert verdict.mismatched[0].status == "checksum-mismatch"
    assert surrogate_release.main(["verify", "--root", str(root)]) == 1


def test_missing_file_is_detected(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "bundle", {"weights/model.pt": b"weights"})
    (root / "weights/model.pt").unlink()

    verdict = verify_bundle(root)

    assert verdict.mismatched[0].status == "missing"
    assert verdict.mismatched[0].actual_sha256 is None


def test_extra_file_outside_inventory_is_reported(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "bundle", {"weights/model.pt": b"weights"})
    (root / "stray.bin").write_bytes(b"stray")

    assert verify_bundle(root).extra_files == ("stray.bin",)


def test_cli_verify_reports_zero_on_intact_bundle(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "bundle", {"weights/model.pt": b"weights"})

    assert surrogate_release.main(["verify", "--root", str(root), "--json"]) == 0


def test_bundle_without_inventory_refuses_to_report_success(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()

    with pytest.raises(RuntimeArtifactError, match="release.json"):
        verify_bundle(root)


def test_empty_inventory_is_an_error_not_a_silent_pass(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "release.json").write_text(
        json.dumps({"format": "aios.surrogate-release.v1", "files_sha256": {}})
    )

    with pytest.raises(RuntimeArtifactError, match="files_sha256"):
        verify_bundle(root)


def test_inventory_escaping_the_bundle_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "release.json").write_text(
        json.dumps(
            {
                "format": "aios.surrogate-release.v1",
                "files_sha256": {"../outside.pt": "0" * 64},
            }
        )
    )

    with pytest.raises(RuntimeArtifactError, match="escapes the bundle"):
        verify_bundle(root)


def test_blend_weight_and_head_version_reach_provenance() -> None:
    record = npv_blend_provenance(_Head())

    assert record["npv_physical_weight"] == repr(0.2)
    assert record["npv_direct_weight"] == repr(0.8)
    assert record["npv_head_version"] == "v" * 64
    assert record["npv_blend_mode"] == "physical-blend"
    assert record["npv_physical_ensemble_version"] == "e" * 64
    assert record["npv_blend_provenance_hash"] == "b" * 64


def test_absent_head_is_reported_not_faked() -> None:
    record = npv_blend_provenance(None)

    assert record["npv_physical_weight"] == "none"
    assert record["npv_head_version"] == "none"


def test_head_without_blend_weight_raises_instead_of_defaulting() -> None:
    class _Anonymous:
        version = "z" * 64

    with pytest.raises(ScheduleSearchError, match="physical_npv_weight"):
        npv_blend_provenance(_Anonymous())


def test_blend_weight_outside_unit_interval_is_rejected() -> None:
    head = _Head()
    head.physical_npv_weight = 1.5

    with pytest.raises(ScheduleSearchError, match="outside \\[0, 1\\]"):
        npv_blend_provenance(head)


def test_matching_lambda_is_recorded_as_match(tmp_path: Path) -> None:
    influence = _lambda(0.5)

    record = lambda_sync_provenance(
        influence, _context(influence), tmp_path / "lambda.json", strict=False
    )

    assert record["lambda_sync"] == "match"
    assert record["lambda_search_hash"] == record["lambda_context_hashes"]
    assert record["lambda_strict"] == "false"
    assert record["lambda_context_source_hash"] == "s" * 64


def test_desync_is_a_warning_in_provenance_not_a_crash(tmp_path: Path) -> None:
    record = lambda_sync_provenance(
        _lambda(0.5), _context(_lambda(0.9)), tmp_path / "lambda.json", strict=False
    )

    assert record["lambda_sync"] == "desync"
    assert record["lambda_search_hash"] != record["lambda_context_hashes"]
    assert "systematically biased" in record["lambda_sync_detail"]


def test_desync_in_strict_mode_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(LambdaDesyncError, match="matches none of the windows"):
        lambda_sync_provenance(
            _lambda(0.5), _context(_lambda(0.9)), tmp_path / "lambda.json", strict=True
        )


def test_context_without_lambda_windows_is_unknown_not_match(tmp_path: Path) -> None:
    record = lambda_sync_provenance(
        _lambda(0.5), _context(None), tmp_path / "lambda.json", strict=False
    )

    assert record["lambda_sync"] == "unknown"


def test_context_without_lambda_windows_is_strict_error(tmp_path: Path) -> None:
    with pytest.raises(LambdaDesyncError, match="contains no . window"):
        lambda_sync_provenance(
            _lambda(0.5), _context(None), tmp_path / "lambda.json", strict=True
        )


def test_trivial_connectivity_has_nothing_to_compare() -> None:
    record = lambda_sync_provenance(
        _lambda(0.5), _context(_lambda(0.9)), None, strict=True
    )

    assert record["lambda_sync"] == "not-applicable"


def test_strict_flag_reads_the_environment() -> None:
    assert _lambda_strict_enabled({}) is False
    assert _lambda_strict_enabled({"AIOS_LAMBDA_STRICT": "1"}) is True
    assert _lambda_strict_enabled({"AIOS_LAMBDA_STRICT": "true"}) is True
    assert _lambda_strict_enabled({"AIOS_LAMBDA_STRICT": "0"}) is False


def test_production_lambda_matches_the_trained_context() -> None:
    lambda_path = data_root() / "lambda-window-2007" / "lambda.json"
    context_path = (
        data_root() / "model-night-20260826-v2" / "feature_context.json"
    )
    if not lambda_path.is_file() or not context_path.is_file():
        pytest.skip("production artifacts are not installed")

    record = lambda_sync_provenance(
        load_lambda(lambda_path),
        ModelZFeatureArtifact.load(context_path),
        lambda_path,
        strict=True,
    )

    assert record["lambda_sync"] == "match"


def test_production_bundle_verifies_against_release_json() -> None:
    root = data_root()
    if not (root / "release.json").is_file():
        pytest.skip("production release inventory is not installed")

    verdict = verify_bundle(root)

    assert verdict.mismatched == (), verdict.as_dict()["mismatches"]
    assert verdict.exit_code == 0


def test_corrupting_a_real_production_file_is_detected(tmp_path: Path) -> None:
    source = data_root()
    if not (source / "release.json").is_file():
        pytest.skip("production release inventory is not installed")
    inventory = json.loads((source / "release.json").read_text(encoding="utf-8"))
    copy = tmp_path / "bundle"
    copy.mkdir()
    shutil.copy2(source / "release.json", copy / "release.json")
    for name in inventory["files_sha256"]:
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)

    assert verify_bundle(copy).ok

    victim = copy / sorted(inventory["files_sha256"])[0]
    victim.write_bytes(victim.read_bytes() + b"\x00tampered")
    verdict = verify_bundle(copy)

    assert not verdict.ok
    assert verdict.exit_code == 1
    assert verdict.mismatched[0].path == sorted(inventory["files_sha256"])[0]
    assert surrogate_release.main(["verify", "--root", str(copy), "--json"]) == 1
