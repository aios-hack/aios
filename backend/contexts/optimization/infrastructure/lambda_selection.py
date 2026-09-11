from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.contexts.optimization.domain.errors import RuntimeArtifactError
from backend.shared.paths import project_root


LAMBDA_SELECTION_FORMAT = "aios.lambda-selection.v1"
DEFAULT_LAMBDA_SELECTION = "config/lambda-selection.json"
LAMBDA_PATH_ENV = "AIOS_LAMBDA_PATH"
LAMBDA_SELECTION_ENV = "AIOS_LAMBDA_SELECTION_PATH"


@dataclass(frozen=True, slots=True)
class LambdaSelection:
    path: Path
    name: str
    origin: str
    selection_path: Path | None
    rationale: str
    expected_feature_context_sha256: str | None
    feature_context_match: str

    def as_provenance(self) -> dict[str, str]:
        return {
            "lambda_path": str(self.path),
            "lambda_selection": self.name,
            "lambda_selection_origin": self.origin,
            "lambda_selection_source": (
                "none" if self.selection_path is None else str(self.selection_path)
            ),
            "lambda_selection_rationale": self.rationale,
            "lambda_expected_feature_context_sha256": (
                self.expected_feature_context_sha256 or "unrecorded"
            ),
            "lambda_feature_context_match": self.feature_context_match,
        }


def _read_lambda_selection_document(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeArtifactError(
            f"λ selection configuration {path} is not readable: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeArtifactError(
            f"{path}: the λ selection configuration is not an object"
        )
    if payload.get("format") != LAMBDA_SELECTION_FORMAT:
        raise RuntimeArtifactError(
            f"unsupported λ selection configuration format {path}: "
            f"{payload.get('format')!r}"
        )
    return payload


def _lambda_candidate(
    path: Path, payload: Mapping[str, object]
) -> tuple[str, Mapping[str, object]]:
    selected = payload.get("selected")
    if not isinstance(selected, str) or not selected:
        raise RuntimeArtifactError(
            f"{path}: the selected field names no λ candidate — the choice must be "
            "recorded explicitly, not substituted by a default"
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, dict) or not candidates:
        raise RuntimeArtifactError(
            f"{path}: the candidates section is empty, there is nothing to choose from"
        )
    candidate = candidates.get(selected)
    if not isinstance(candidate, dict):
        raise RuntimeArtifactError(
            f"{path}: λ candidate {selected!r} is selected but absent from candidates"
        )
    return selected, candidate


def _lambda_rationale(path: Path, name: str, candidate: Mapping[str, object]) -> str:
    rationale = candidate.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise RuntimeArtifactError(
            f"{path}: λ candidate {name!r} is recorded without a rationale — a choice "
            "without a reason is indistinguishable from a default, and the "
            "provenance must carry it"
        )
    return rationale.strip()


def _lambda_feature_context_match(
    expected: str | None, feature_context: Path | None
) -> str:
    if expected is None:
        return "unrecorded"
    if feature_context is None:
        return "not-checked"
    if not feature_context.is_file():
        raise RuntimeArtifactError(
            f"feature context {feature_context} is not readable: there is nothing to "
            "check λ against the model features with"
        )
    actual = hashlib.sha256(feature_context.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeArtifactError(
            f"λ was selected as an export from the feature context with "
            f"feature_context_sha256={expected}, while the production context "
            f"{feature_context} has {actual}: the search connectivity and the "
            "model features diverged, and the search result would refer to a "
            "different matrix"
        )
    return "identical"


def resolve_lambda_selection(
    environ: Mapping[str, str] | None = None,
    feature_context: Path | None = None,
) -> LambdaSelection:
    env = os.environ if environ is None else environ
    root_override = env.get("AIOS_PROJECT_ROOT")
    root = Path(root_override).expanduser().resolve() if root_override else project_root()
    configured = env.get(LAMBDA_SELECTION_ENV)
    selection_path = Path(configured) if configured else root / DEFAULT_LAMBDA_SELECTION
    override = env.get(LAMBDA_PATH_ENV)
    if override:
        return LambdaSelection(
            path=Path(override),
            name="environment-override",
            origin="environment-override",
            selection_path=selection_path if selection_path.is_file() else None,
            rationale=(
                f"{LAMBDA_PATH_ENV}={override!r} overrides the λ selection configuration: "
                "the matrix originates from an explicit operator decision rather "
                "than a configuration entry, and no check against the feature "
                "context was performed"
            ),
            expected_feature_context_sha256=None,
            feature_context_match="not-checked",
        )
    if configured and not selection_path.is_file():
        raise RuntimeArtifactError(
            f"{LAMBDA_SELECTION_ENV}={configured} points at a missing λ selection "
            "configuration"
        )
    if not selection_path.is_file():
        raise RuntimeArtifactError(
            f"there is no λ selection configuration at {selection_path}: the path to "
            "the connectivity matrix is set by the configuration, and "
            "substituting a module constant is forbidden — the search would "
            "optimize against an unknown λ"
        )
    payload = _read_lambda_selection_document(selection_path)
    name, candidate = _lambda_candidate(selection_path, payload)
    raw_path = candidate.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise RuntimeArtifactError(
            f"{selection_path}: λ candidate {name!r} is recorded without a path to the artifact"
        )
    lambda_path = Path(raw_path)
    if not lambda_path.is_absolute():
        lambda_path = root / lambda_path
    if not lambda_path.is_file():
        raise RuntimeArtifactError(
            f"{selection_path}: the selected λ {name!r} is missing at path "
            f"{lambda_path}"
        )
    rationale = _lambda_rationale(selection_path, name, candidate)
    raw_expected = candidate.get("expected_feature_context_sha256")
    expected: str | None = None
    if raw_expected is not None:
        if not isinstance(raw_expected, str) or len(raw_expected) != 64:
            raise RuntimeArtifactError(
                f"{selection_path}: λ candidate {name!r} declared an "
                "expected_feature_context_sha256 that is not a SHA-256"
            )
        expected = raw_expected.lower()
    match = _lambda_feature_context_match(expected, feature_context)
    return LambdaSelection(
        path=lambda_path,
        name=name,
        origin="selection-config",
        selection_path=selection_path,
        rationale=rationale,
        expected_feature_context_sha256=expected,
        feature_context_match=match,
    )

