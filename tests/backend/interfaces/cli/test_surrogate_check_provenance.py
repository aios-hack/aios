from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from backend.contexts.optimization.application.environment import (
    LambdaDesyncError,
    lambda_sync_provenance,
    npv_blend_provenance,
)
from backend.core.contracts import Lambda
from backend.core.paths import data_root
from backend.contexts.connectivity.domain.measure import load_lambda
from backend.contexts.surrogate.infrastructure.model_z_context import ModelZFeatureArtifact
from backend.interfaces.cli.surrogate import check as _check

LAMBDA_PATH = data_root() / "lambda-window-2007" / "lambda.json"
CONTEXT_PATH = data_root() / "model-night-20260826-v2" / "feature_context.json"


def _artifacts_installed() -> bool:
    return LAMBDA_PATH.is_file() and CONTEXT_PATH.is_file()


def _payload(provenance: dict[str, str], bundle_status: str | None = None) -> dict:
    payload: dict = {"provenance": provenance}
    if bundle_status is not None:
        payload["bundle"] = {"status": bundle_status}
    return payload


def test_lambda_artifact_provenance_names_every_missing_field() -> None:
    if not _artifacts_installed():
        pytest.skip("production artifacts are not installed")

    record = surrogate_check._lambda_artifact_provenance(LAMBDA_PATH)

    assert set(record) >= {
        "lambda_artifact_artifact_id",
        "lambda_artifact_measured_at",
        "lambda_artifact_n_runs",
        "lambda_artifact_source_run_ids",
        "lambda_artifact_code_version",
        "lambda_artifact_provenance_recorded",
        "lambda_artifact_missing_fields",
    }
    if record["lambda_artifact_provenance_recorded"] == "false":
        assert record["lambda_artifact_missing_fields"] != "none"
        assert "unrecorded" in record.values()


def test_blend_weight_and_head_version_are_in_the_check_provenance() -> None:
    head = SimpleNamespace(
        version="h" * 64,
        physical_npv_weight=0.2,
        physical_ensemble_version="e" * 64,
        physical_blend_provenance_hash="b" * 64,
    )

    record = npv_blend_provenance(head)

    assert record["npv_physical_weight"] == repr(0.2)
    assert record["npv_direct_weight"] == repr(0.8)
    assert record["npv_head_version"] == "h" * 64
    assert record["npv_blend_mode"] == "physical-blend"


def test_production_lambda_and_context_agree() -> None:
    if not _artifacts_installed():
        pytest.skip("production artifacts are not installed")

    record = lambda_sync_provenance(
        load_lambda(LAMBDA_PATH),
        ModelZFeatureArtifact.load(CONTEXT_PATH),
        LAMBDA_PATH,
        strict=True,
    )

    assert record["lambda_sync"] == "match"
    assert record["lambda_path"] == str(LAMBDA_PATH)


def test_shifted_production_lambda_desyncs_and_is_strict_error() -> None:
    if not _artifacts_installed():
        pytest.skip("production artifacts are not installed")

    genuine = load_lambda(LAMBDA_PATH)
    context = ModelZFeatureArtifact.load(CONTEXT_PATH)
    shifted = Lambda(
        window_start=genuine.window_start,
        window_end=genuine.window_end,
        producers=genuine.producers,
        injectors=genuine.injectors,
        matrix=tuple(
            tuple(value * 2.0 for value in row) for row in genuine.matrix
        ),
        lag_months=genuine.lag_months,
        amplitude=genuine.amplitude,
        stability=genuine.stability,
        rank=genuine.rank,
        condition_number=genuine.condition_number,
        achievability_ok=dict(genuine.achievability_ok),
    )

    warned = lambda_sync_provenance(shifted, context, LAMBDA_PATH, strict=False)
    assert warned["lambda_sync"] == "desync"

    with pytest.raises(LambdaDesyncError):
        lambda_sync_provenance(shifted, context, LAMBDA_PATH, strict=True)


def test_exit_code_is_nonzero_on_lambda_desync() -> None:
    assert surrogate_check.exit_code_for(_payload({"lambda_sync": "desync"})) == 1
    assert surrogate_check.exit_code_for(_payload({"lambda_sync": "match"})) == 0
    assert surrogate_check.exit_code_for(_payload({"lambda_sync": "unknown"})) == 0


def test_exit_code_is_nonzero_on_corrupted_bundle() -> None:
    clean = _payload({"lambda_sync": "match"}, bundle_status="ok")
    dirty = _payload({"lambda_sync": "match"}, bundle_status="corrupted")

    assert surrogate_check.exit_code_for(clean) == 0
    assert surrogate_check.exit_code_for(dirty) == 1


def test_strict_desync_exits_with_error_code(monkeypatch, capsys) -> None:
    def _explode(*args: object, **kwargs: object) -> dict:
        raise LambdaDesyncError("λ поиска разошлась с λ обучения контекста")

    monkeypatch.setattr(surrogate_check, "check", _explode)

    code = surrogate_check.main(["--lambda-strict"])

    assert code == 2
    assert "строгий режим" in capsys.readouterr().err


def test_check_payload_carries_blend_and_lambda_sync(monkeypatch, tmp_path) -> None:
    provenance = MappingProxyType(
        {
            "npv_physical_weight": repr(0.2),
            "npv_direct_weight": repr(0.8),
            "npv_head_version": "h" * 64,
            "npv_blend_mode": "physical-blend",
            "lambda_sync": "desync",
            "lambda_search_hash": "1" * 64,
            "lambda_context_hashes": "2" * 64,
        }
    )
    env = SimpleNamespace(
        provenance=provenance,
        npv_head=SimpleNamespace(version="h" * 64),
        model=SimpleNamespace(
            version="m" * 64,
            dataset_hash="d" * 64,
            predict=lambda _input: SimpleNamespace(output=object()),
        ),
        scenario_ood=SimpleNamespace(version="o" * 64, threshold=0.5),
        base_schedule=object(),
        feature_context=SimpleNamespace(context=object()),
        oil_density_t_per_m3=0.9131,
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    influence = tmp_path / "lambda.json"

    monkeypatch.setattr(
        surrogate_check, "resolve_runtime_artifacts", lambda _env: SimpleNamespace(
            checkpoint=tmp_path / "c.json",
            feature_context=tmp_path / "f.json",
            npv_head=tmp_path / "h.pt",
            scenario_ood=tmp_path / "o.pt",
        )
    )
    monkeypatch.setattr(surrogate_check, "load_environment", lambda **_: env)
    monkeypatch.setattr(surrogate_check, "validate_runtime_economic_head", lambda *_: None)
    monkeypatch.setattr(
        surrogate_check, "make_evaluator",
        lambda _env: lambda _schedule: SimpleNamespace(npv=1.0, ood_score=0.1),
    )
    monkeypatch.setattr(
        surrogate_check,
        "_prediction_block",
        lambda _env, _evaluator, _schedule, note: {
            "schedule_hash": "s" * 64,
            "predicted_npv_rub": 1.0,
            "npv_parts": {},
            "ood_score": 0.1,
            "ood_worst": None,
            "ood_exceedances": [],
            "blocking_physics": 0,
            "physics_counts": {},
            "physics_complete": True,
            "physics_admissible": True,
            "physics_gate": "off",
            "physics_gate_note": note,
            "invariants_evaluated": [],
            "invariants_not_checked": [],
            "invariants_skip_reasons": {},
            "differential_invariants_checked": False,
        },
    )
    monkeypatch.setattr(
        surrogate_check, "ScheduleFeatureizer",
        lambda: SimpleNamespace(
            transform=lambda *_: SimpleNamespace(lambda_edges=("x",))
        ),
    )
    monkeypatch.setattr(
        surrogate_check, "check_prediction",
        lambda *_, **__: SimpleNamespace(blocking_count=0, counts={}),
    )
    monkeypatch.setattr(
        surrogate_check, "_lambda_artifact_provenance",
        lambda _path: {"lambda_artifact_provenance_recorded": "false"},
    )
    monkeypatch.setattr(
        surrogate_check, "replace", lambda candidate, **_: candidate
    )

    payload = surrogate_check.check(manifest, tmp_path / "r.json", influence)

    recorded = payload["provenance"]
    assert recorded["npv_physical_weight"] == repr(0.2)
    assert recorded["npv_head_version"] == "h" * 64
    assert recorded["lambda_sync"] == "desync"
    assert recorded["lambda_artifact_provenance_recorded"] == "false"
    assert surrogate_check.exit_code_for(payload) == 1
    assert json.dumps(payload, ensure_ascii=False, allow_nan=False)
