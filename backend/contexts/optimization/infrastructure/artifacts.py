from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.contexts.optimization.domain.errors import RuntimeArtifactError
from backend.contexts.optimization.infrastructure.lambda_selection import (
    DEFAULT_LAMBDA_SELECTION,
    LAMBDA_PATH_ENV,
    LAMBDA_SELECTION_ENV,
    LAMBDA_SELECTION_FORMAT,
    LambdaSelection,
    resolve_lambda_selection,
)
from backend.contexts.optimization.infrastructure.ood_calibration import (
    CONSERVATIVE_OOD_THRESHOLD,
    DEFAULT_OOD_CALIBRATION,
    OOD_CALIBRATION_FORMAT,
    OodThresholdDecision,
    resolve_ood_threshold,
)
from backend.shared.paths import project_root


RELEASE_FORMAT = "aios.surrogate-release.v1"
RELEASE_FILENAME = "release.json"
INSTALL_MANIFEST_FORMAT = "aios.surrogate-runtime.v1"


@dataclass(frozen=True, slots=True)
class FileVerdict:
    path: str
    expected_sha256: str
    actual_sha256: str | None
    status: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "status": self.status,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
        }


@dataclass(frozen=True, slots=True)
class BundleVerdict:
    root: Path
    reference: Path
    reference_format: str
    files: tuple[FileVerdict, ...]
    extra_files: tuple[str, ...]

    @property
    def mismatched(self) -> tuple[FileVerdict, ...]:
        return tuple(item for item in self.files if not item.ok)

    @property
    def ok(self) -> bool:
        return not self.mismatched

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def as_dict(self) -> dict[str, object]:
        return {
            "format": "aios.surrogate-bundle-verdict.v1",
            "root": str(self.root),
            "reference": str(self.reference),
            "reference_format": self.reference_format,
            "checked_file_count": len(self.files),
            "mismatched_file_count": len(self.mismatched),
            "status": "ok" if self.ok else "corrupted",
            "files": [item.as_dict() for item in self.files],
            "mismatches": [item.as_dict() for item in self.mismatched],
            "extra_files": list(self.extra_files),
        }


def _read_expected_checksums(reference: Path) -> tuple[dict[str, str], str]:
    try:
        payload = json.loads(reference.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeArtifactError(
            f"bundle inventory {reference} is not readable: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeArtifactError(f"bundle inventory {reference} is not an object")
    declared = payload.get("format")
    if declared not in {RELEASE_FORMAT, INSTALL_MANIFEST_FORMAT}:
        raise RuntimeArtifactError(
            f"unsupported bundle inventory format {reference}: {declared!r}"
        )
    checksums = payload.get("files_sha256")
    if not isinstance(checksums, dict) or not checksums:
        raise RuntimeArtifactError(
            f"{reference}: an inventory without files_sha256 defines no checksum — "
            "there is nothing to verify, and a silent success would mean an "
            "unverified bundle"
        )
    expected: dict[str, str] = {}
    for name, digest in checksums.items():
        if not isinstance(name, str) or not isinstance(digest, str) or len(digest) != 64:
            raise RuntimeArtifactError(
                f"{reference}: inventory entry {name!r} is not a "
                "\"path — SHA-256\" pair"
            )
        expected[name] = digest.lower()
    return expected, str(declared)


def _bundle_reference(root: Path) -> Path:
    release = root / RELEASE_FILENAME
    if release.is_file():
        return release
    raise RuntimeArtifactError(
        f"bundle {root} has no {RELEASE_FILENAME}: without an inventory with "
        "checksums no integrity verdict can be issued"
    )


def verify_bundle(root: Path | str, reference: Path | str | None = None) -> BundleVerdict:
    bundle_root = Path(root).resolve()
    if not bundle_root.is_dir():
        raise RuntimeArtifactError(f"bundle {bundle_root} is not a directory")
    reference_path = (
        _bundle_reference(bundle_root) if reference is None else Path(reference).resolve()
    )
    if not reference_path.is_file():
        raise RuntimeArtifactError(f"there is no bundle inventory at {reference_path}")
    expected, reference_format = _read_expected_checksums(reference_path)
    verdicts: list[FileVerdict] = []
    for name in sorted(expected):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeArtifactError(
                f"{reference_path}: inventory entry {name!r} escapes the bundle"
            )
        target = bundle_root / relative
        if not target.is_file():
            verdicts.append(FileVerdict(name, expected[name], None, "missing"))
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        status = "ok" if actual == expected[name] else "checksum-mismatch"
        verdicts.append(FileVerdict(name, expected[name], actual, status))
    known = {(bundle_root / Path(name)).resolve() for name in expected}
    known.add(reference_path)
    extra = tuple(
        sorted(
            path.relative_to(bundle_root).as_posix()
            for path in bundle_root.rglob("*")
            if path.is_file() and path.resolve() not in known
        )
    )
    return BundleVerdict(
        root=bundle_root,
        reference=reference_path,
        reference_format=reference_format,
        files=tuple(verdicts),
        extra_files=extra,
    )


@dataclass(frozen=True, slots=True)
class RuntimeArtifacts:
    checkpoint: Path
    feature_context: Path
    npv_head: Path | None
    source: str
    scenario_ood: Path | None = None
    economic_model_version: str | None = None
    economic_target_provenance_hash: str | None = None
    npv_calibration: Path | None = None


def validate_npv_scoring_is_unambiguous(artifacts: RuntimeArtifacts) -> None:
    if artifacts.npv_calibration is None or artifacts.npv_head is None:
        return
    raise RuntimeArtifactError(
        "an affine NPV calibration "
        f"({artifacts.npv_calibration}) and a direct forecast head "
        f"({artifacts.npv_head}) are set at the same time: the calibration was "
        "fitted on the raw physical NPV and does not apply to the head blend, so "
        "the final number would be computed by something other than what is "
        "declared; keep one mechanism — remove either "
        "AIOS_NPV_CALIBRATION_PATH or AIOS_NPV_HEAD_PATH"
    )


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
    explicit_calibration = env.get("AIOS_NPV_CALIBRATION_PATH")
    manifest_value = env.get("AIOS_SURROGATE_MANIFEST")
    bundle_value = env.get("AIOS_SURROGATE_BUNDLE")
    legacy_dir = env.get("AIOS_CHECKPOINT_DIR")
    default_bundle = project_root() / "data" / "model-production"
    default_manifest = project_root() / "data" / "surrogate-production.json"
    economic_model_version: str | None = None
    economic_target_provenance_hash: str | None = None

    payload = {}
    scenario_ood = None

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

    if source.startswith("production manifest"):
        guard = payload.get("scenario_ood")
        if not isinstance(guard, dict) or not guard.get("path") or not guard.get("sha256"):
            raise RuntimeArtifactError("production manifest requires a versioned scenario_ood artifact")
        scenario_ood = manifest.parent / guard["path"]
        if not scenario_ood.is_file():
            raise RuntimeArtifactError(f"missing runtime artifact: {scenario_ood}")
        if hashlib.sha256(scenario_ood.read_bytes()).hexdigest() != guard["sha256"]:
            raise RuntimeArtifactError("scenario OOD checksum differs from production manifest")
        if not context.is_file() or hashlib.sha256(context.read_bytes()).hexdigest() != guard.get("feature_context_sha256"):
            raise RuntimeArtifactError("scenario OOD feature context differs from production manifest")
    elif env.get("AIOS_SCENARIO_OOD_PATH"):
        scenario_ood = Path(env["AIOS_SCENARIO_OOD_PATH"])

    calibration: Path | None = None
    if explicit_calibration:
        calibration = Path(explicit_calibration)
    elif payload.get("npv_calibration"):
        calibration = manifest.parent / payload["npv_calibration"]

    required = (checkpoint, context) + ((scenario_ood,) if scenario_ood is not None else ())
    missing = [str(path) for path in required if not path.is_file()]
    if head is not None and not head.is_file():
        if explicit_head or manifest_value or source.startswith("production manifest"):
            missing.append(str(head))
        else:
            head = None
    if calibration is not None and not calibration.is_file():
        missing.append(str(calibration))
    if missing:
        raise RuntimeArtifactError(
            f"{source}: missing runtime artifact(s): {', '.join(missing)}"
        )
    artifacts = RuntimeArtifacts(
        checkpoint=checkpoint,
        feature_context=context,
        npv_head=head,
        source=source,
        scenario_ood=scenario_ood,
        economic_model_version=economic_model_version,
        economic_target_provenance_hash=economic_target_provenance_hash,
        npv_calibration=calibration,
    )
    validate_npv_scoring_is_unambiguous(artifacts)
    return artifacts
