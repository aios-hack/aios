from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace

import pytest

from backend.contexts.optimization.infrastructure.artifacts import (
    RuntimeArtifactError,
    RuntimeArtifacts,
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)


def test_bundle_resolves_ensemble_and_bundle_context(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "physical").mkdir(parents=True)
    (bundle / "physical" / "trajectory_ensemble.json").write_text(
        json.dumps({"format": "test"})
    )
    (bundle / "physical" / "npv_head.pt").write_text("head")
    (bundle / "feature_context.json").write_text("{}")

    result = resolve_runtime_artifacts({"AIOS_SURROGATE_BUNDLE": str(bundle)})

    assert result.checkpoint == bundle / "physical" / "trajectory_ensemble.json"
    assert result.feature_context == bundle / "feature_context.json"
    assert result.npv_head == bundle / "physical" / "npv_head.pt"


def test_explicit_ensemble_finds_context_at_bundle_level(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "physical").mkdir(parents=True)
    checkpoint = bundle / "physical" / "trajectory_ensemble.json"
    checkpoint.write_text("{}")
    context = bundle / "feature_context.json"
    context.write_text("{}")

    result = resolve_runtime_artifacts({"AIOS_CHECKPOINT_PATH": str(checkpoint)})

    assert result.feature_context == context
    assert result.source == "explicit checkpoint"


def test_missing_bundle_fails_instead_of_using_an_old_model(tmp_path) -> None:
    with pytest.raises(RuntimeArtifactError, match="missing runtime artifact"):
        resolve_runtime_artifacts({"AIOS_SURROGATE_BUNDLE": str(tmp_path / "absent")})


def test_manifest_can_switch_only_the_economic_head(tmp_path) -> None:
    data = tmp_path / "data"
    physical = data / "physical"
    physical.mkdir(parents=True)
    checkpoint = physical / "trajectory.json"
    context = data / "context.json"
    head = data / "candidate.pt"
    for path in (checkpoint, context, head):
        path.write_text("artifact")
    guard = data / "scenario.pt"
    guard.write_bytes(b"guard")
    manifest = data / "production.json"
    manifest.write_text(
        json.dumps(
            {
                "format": "aios.surrogate-production-pointer.v1",
                "trajectory_checkpoint": "physical/trajectory.json",
                "feature_context": "context.json",
                "npv_head": "candidate.pt",
                "scenario_ood": {"path": "scenario.pt", "sha256": hashlib.sha256(guard.read_bytes()).hexdigest(), "feature_context_sha256": hashlib.sha256(context.read_bytes()).hexdigest()},
                "active_economic_model_version": "candidate-v1",
                "active_economic_target_provenance_hash": "t" * 64,
            }
        )
    )

    result = resolve_runtime_artifacts({"AIOS_SURROGATE_MANIFEST": str(manifest)})

    assert result.checkpoint == checkpoint
    assert result.feature_context == context
    assert result.npv_head == head
    assert result.scenario_ood == guard
    assert result.economic_model_version == "candidate-v1"
    assert result.economic_target_provenance_hash == "t" * 64
    validate_runtime_economic_head(
        result,
        SimpleNamespace(version="candidate-v1", target_provenance_hash="t" * 64),
    )


def test_manifest_target_provenance_mismatch_is_rejected(tmp_path) -> None:
    artifacts = RuntimeArtifacts(
        checkpoint=tmp_path / "trajectory.json",
        feature_context=tmp_path / "context.json",
        npv_head=tmp_path / "head.pt",
        source="test",
        economic_model_version="v4",
        economic_target_provenance_hash="a" * 64,
    )

    with pytest.raises(RuntimeArtifactError, match="target provenance"):
        validate_runtime_economic_head(
            artifacts,
            SimpleNamespace(version="v4", target_provenance_hash="b" * 64),
        )


@pytest.mark.parametrize('problem', ['missing_manifest_field', 'missing_file', 'wrong_checksum', 'changed_context'])
def test_production_cannot_silently_disable_scenario_ood(tmp_path, problem):
    for name in ('trajectory.json', 'context.json', 'head.pt', 'domain.pt'):
        (tmp_path / name).write_bytes(b'artifact')
    payload = {
        'format': 'aios.surrogate-production-pointer.v1',
        'trajectory_checkpoint': 'trajectory.json',
        'feature_context': 'context.json', 'npv_head': 'head.pt',
        'scenario_ood': {'path': 'domain.pt', 'sha256': hashlib.sha256(b'artifact').hexdigest(), 'feature_context_sha256': hashlib.sha256(b'artifact').hexdigest()},
    }
    if problem == 'missing_manifest_field':
        del payload['scenario_ood']
    elif problem == 'missing_file':
        (tmp_path / 'domain.pt').unlink()
    elif problem == 'changed_context':
        (tmp_path / 'context.json').write_bytes(b'changed')
    else:
        (tmp_path / 'domain.pt').write_bytes(b'changed')
    manifest = tmp_path / 'production.json'
    manifest.write_text(json.dumps(payload))
    with pytest.raises(RuntimeArtifactError):
        resolve_runtime_artifacts({'AIOS_SURROGATE_MANIFEST': str(manifest)})


@pytest.fixture(autouse=True)
def isolated_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.contexts.optimization.infrastructure.artifacts.project_root", lambda: tmp_path)
