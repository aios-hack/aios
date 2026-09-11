from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.runs.domain.run_result import SubmissionBundle
from backend.contexts.schedule.domain.schedule import Schedule


class WorkflowStatus(Enum):
    SEARCHED = "searched"
    VERIFIED = "verified"
    REJECTED = "rejected"
    READY_TO_SUBMIT = "ready_to_submit"


class Verification(Protocol):
    sound: bool
    npv_methodology: float | None


@dataclass(frozen=True, slots=True)
class RunProvenance:
    model_version: str | None = None
    npv_head_version: str | None = None
    scenario_ood_version: str | None = None
    feature_context_sha256: str | None = None
    constraints_hash: str | None = None
    deck_hash: str | None = None
    normatives_sha256: str | None = None
    opm_image: str | None = None
    git_commit: str | None = None
    seed: str | None = None
    search_strategy: str | None = None
    policy_equilibrium: str | None = None
    iterations: int | None = None
    self_consistent: bool | None = None


@dataclass(frozen=True, slots=True)
class RunRequest:
    run_id: str
    schedule: Schedule
    predicted_npv: float | None = None
    constraints: Constraints | None = None
    provenance: RunProvenance = RunProvenance()


MANIFEST_PROVENANCE_FIELDS: tuple[str, ...] = (
    "model_version",
    "npv_head_version",
    "scenario_ood_version",
    "feature_context_sha256",
    "constraints_hash",
    "deck_hash",
    "normatives_sha256",
    "opm_image",
    "git_commit",
    "seed",
    "search_strategy",
    "policy_equilibrium",
    "iterations",
    "self_consistent",
)


MANIFEST_FIELDS: tuple[str, ...] = (
    "run_id",
    "status",
    "schedule_hash",
    "predicted_npv",
    "verified_npv",
    "sound",
) + MANIFEST_PROVENANCE_FIELDS


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    status: WorkflowStatus
    schedule_hash: str
    predicted_npv: float | None
    verified_npv: float | None
    sound: bool | None
    model_version: str | None = None
    npv_head_version: str | None = None
    scenario_ood_version: str | None = None
    feature_context_sha256: str | None = None
    constraints_hash: str | None = None
    deck_hash: str | None = None
    normatives_sha256: str | None = None
    opm_image: str | None = None
    git_commit: str | None = None
    seed: str | None = None
    search_strategy: str | None = None
    policy_equilibrium: str | None = None
    iterations: int | None = None
    self_consistent: bool | None = None

    @classmethod
    def from_dict(cls, document: dict[str, object]) -> RunManifest:
        missing = [
            name
            for name in ("run_id", "status", "schedule_hash")
            if name not in document
        ]
        if missing:
            raise ValueError(
                "the run manifest is incomplete, required fields are missing: "
                + ", ".join(missing)
            )
        known = {
            name: document.get(name)
            for name in MANIFEST_FIELDS
            if name != "status"
        }
        return cls(status=WorkflowStatus(document["status"]), **known)

    def as_dict(self) -> dict[str, object]:
        document: dict[str, object] = {
            "run_id": self.run_id,
            "status": self.status.value,
            "schedule_hash": self.schedule_hash,
            "predicted_npv": self.predicted_npv,
            "verified_npv": self.verified_npv,
            "sound": self.sound,
        }
        for name in MANIFEST_PROVENANCE_FIELDS:
            document[name] = getattr(self, name)
        return document


SUBMISSION_BUNDLE_FIELDS: tuple[str, ...] = (
    "canonical_schedule_hash",
    "content_hash_submission",
    "claimed_npv_rub",
    "source_run_id",
    "response_hash",
    "deck_hash",
    "economics_config_hash",
    "methodology_version_hash",
    "constraints_hash",
    "opm_image",
    "git_commit",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class SubmissionReport:
    manifest: RunManifest
    bundle: SubmissionBundle
    directory: Path
    schedule_path: Path
