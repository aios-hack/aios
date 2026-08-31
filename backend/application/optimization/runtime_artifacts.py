"""Resolve production surrogate artifacts without silent fallback."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.core.paths import project_root


class RuntimeArtifactError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeArtifacts:
    checkpoint: Path
    feature_context: Path
    npv_head: Path | None
    source: str
    economic_model_version: str | None = None
    economic_target_provenance_hash: str | None = None


def validate_runtime_economic_head(
    artifacts: RuntimeArtifacts, head: object | None
) -> None:
    if artifacts.economic_model_version is None:
        return
    if head is None:
        raise RuntimeArtifactError("production manifest requires an economic head")
    if getattr(head, "version", None) != artifacts.economic_model_version:
        raise RuntimeArtifactError("economic head version differs from production manifest")
    expected_target = artifacts.economic_target_provenance_hash or ""
    if getattr(head, "target_provenance_hash", "") != expected_target:
        raise RuntimeArtifactError(
            "economic target provenance differs from production manifest"
        )


def _feature_next_to_checkpoint(checkpoint: Path) -> Path:
    adjacent = checkpoint.parent / "feature_context.json"
    if adjacent.is_file():
        return adjacent
    return checkpoint.parent.parent / "feature_context.json"


def _read_pointer(manifest: Path) -> dict:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeArtifactError(f"invalid production manifest {manifest}: {error}") from error
    if payload.get("format") != "aios.surrogate-production-pointer.v1":
        raise RuntimeArtifactError(f"unsupported production manifest: {manifest}")
    return payload


def resolve_runtime_artifacts(
    environ: Mapping[str, str] | None = None,
) -> RuntimeArtifacts:
    env = os.environ if environ is None else environ
    explicit_checkpoint = env.get("AIOS_CHECKPOINT_PATH")
    explicit_context = env.get("AIOS_FEATURE_CONTEXT_PATH")
    explicit_head = env.get("AIOS_NPV_HEAD_PATH")
    manifest_value = env.get("AIOS_SURROGATE_MANIFEST")
    bundle_value = env.get("AIOS_SURROGATE_BUNDLE")
    legacy_dir = env.get("AIOS_CHECKPOINT_DIR")
    default_bundle = project_root() / "data" / "model-production"
    default_manifest = project_root() / "data" / "surrogate-production.json"
    economic_model_version: str | None = None
    economic_target_provenance_hash: str | None = None

    if explicit_checkpoint:
        checkpoint = Path(explicit_checkpoint)
        context = Path(explicit_context) if explicit_context else _feature_next_to_checkpoint(checkpoint)
        head = Path(explicit_head) if explicit_head else checkpoint.parent / "npv_head.pt"
        source = "explicit checkpoint"
    elif manifest_value or default_manifest.is_file():
        manifest = Path(manifest_value) if manifest_value else default_manifest
        payload = _read_pointer(manifest)
        checkpoint = manifest.parent / payload["trajectory_checkpoint"]
        context = manifest.parent / payload["feature_context"]
        head = Path(explicit_head) if explicit_head else manifest.parent / payload["npv_head"]
        if not explicit_head:
            economic_model_version = payload.get("active_economic_model_version")
            economic_target_provenance_hash = payload.get(
                "active_economic_target_provenance_hash", ""
            )
        source = f"production manifest {manifest}"
    elif bundle_value:
        bundle = Path(bundle_value)
        checkpoint = bundle / "physical" / "trajectory_ensemble.json"
        context = Path(explicit_context) if explicit_context else bundle / "feature_context.json"
        head = Path(explicit_head) if explicit_head else bundle / "physical" / "npv_head.pt"
        source = "AIOS_SURROGATE_BUNDLE"
    elif legacy_dir:
        directory = Path(legacy_dir)
        ensemble = directory / "trajectory_ensemble.json"
        checkpoint = ensemble if ensemble.is_file() else directory / "model.pt"
        context = Path(explicit_context) if explicit_context else directory / "feature_context.json"
        head = Path(explicit_head) if explicit_head else directory / "npv_head.pt"
        source = "legacy AIOS_CHECKPOINT_DIR"
    else:
        checkpoint = default_bundle / "physical" / "trajectory_ensemble.json"
        context = default_bundle / "feature_context.json"
        head = Path(explicit_head) if explicit_head else default_bundle / "physical" / "npv_head.pt"
        source = "default production bundle"

    missing = [str(path) for path in (checkpoint, context) if not path.is_file()]
    if head is not None and not head.is_file():
        if explicit_head or manifest_value or source.startswith("production manifest"):
            missing.append(str(head))
        else:
            head = None
    if missing:
        raise RuntimeArtifactError(
            f"{source}: missing runtime artifact(s): {', '.join(missing)}"
        )
    return RuntimeArtifacts(
        checkpoint=checkpoint,
        feature_context=context,
        npv_head=head,
        source=source,
        economic_model_version=economic_model_version,
        economic_target_provenance_hash=economic_target_provenance_hash,
    )
