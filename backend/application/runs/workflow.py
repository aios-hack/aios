from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from backend.core.contracts import Constraints, Schedule, canonical_bytes, hash_schedule
from backend.domain.configuration.constraints_io import constraints_to_json


class WorkflowStatus(Enum):
    SEARCHED = "searched"
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
                "манифест прогона неполон, нет обязательных полей: "
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


class RunWorkflow:

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root

    def search(self, request: RunRequest) -> RunManifest:
        run_dir = self._prepare(request)
        manifest = RunManifest(
            run_id=request.run_id,
            status=WorkflowStatus.SEARCHED,
            schedule_hash=hash_schedule(request.schedule),
            predicted_npv=request.predicted_npv,
            verified_npv=None,
            sound=None,
            **_provenance_fields(request.provenance),
        )
        self._write_manifest(run_dir, manifest)
        return manifest

    def verify(
        self, request: RunRequest, verify: Callable[[Schedule, Path], Verification]
    ) -> RunManifest:
        run_dir = self._prepare(request)
        result = verify(request.schedule, run_dir / "opm")
        sound = result.sound
        verified_npv = result.npv_methodology if sound else None
        calculated = getattr(result, 'final_npv', None)
        measured_npv = calculated.npv_methodology if calculated is not None else verified_npv
        fields = _provenance_fields(request.provenance)
        observed_deck_hash = getattr(getattr(result, "opm_run", None), "deck_hash", None)
        if observed_deck_hash:
            fields["deck_hash"] = observed_deck_hash
        manifest = RunManifest(
            run_id=request.run_id,
            status=WorkflowStatus.READY_TO_SUBMIT if sound else WorkflowStatus.REJECTED,
            schedule_hash=hash_schedule(request.schedule),
            predicted_npv=request.predicted_npv,
            verified_npv=verified_npv,
            sound=sound,
            **fields,
        )
        (run_dir / "validation").mkdir(exist_ok=True)
        (run_dir / "validation" / "result.json").write_text(
            json.dumps(
                {
                    "sound": sound,
                    "opm_status": getattr(getattr(result, "opm_run", None), "status", None).value
                    if getattr(getattr(result, "opm_run", None), "status", None) is not None
                    else None,
                    "dynamic_violations": len(getattr(getattr(result, "dynamic_report", None), "violations", ())),
                    "blocking_dynamic_violations": len(getattr(getattr(result, "dynamic_report", None), "blocking_violations", ())),
                    "failed_identities": [item.name for item in getattr(result, "failed_identities", ())],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "economics" / "result.json").write_text(
            json.dumps({"npv_methodology": verified_npv, "measured_npv": measured_npv, "sound": sound}, indent=2) + "\n",
            encoding="utf-8",
        )
        self._write_manifest(run_dir, manifest)
        return manifest

    def full(
        self,
        search: Callable[[], RunRequest],
        verify: Callable[[Schedule, Path], Verification],
    ) -> RunManifest:
        request = search()
        self.search(request)
        return self.verify(request, verify)

    def _prepare(self, request: RunRequest) -> Path:
        if not request.run_id or Path(request.run_id).name != request.run_id:
            raise ValueError("run_id must be one plain directory name")
        run_dir = self.runs_root / request.run_id
        for name in ("inputs", "schedule", "prediction", "opm", "validation", "economics", "ui"):
            (run_dir / name).mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs" / "request.json").write_text(
            json.dumps(
                {
                    "run_id": request.run_id,
                    "schedule_hash": hash_schedule(request.schedule),
                    "predicted_npv": request.predicted_npv,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if request.constraints is not None:
            (run_dir / "inputs" / "constraints.json").write_text(
                json.dumps(
                    constraints_to_json(request.constraints),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        (run_dir / "schedule" / "schedule.json").write_bytes(canonical_bytes(request.schedule))
        (run_dir / "prediction" / "result.json").write_text(
            json.dumps({"npv": request.predicted_npv}, indent=2) + "\n", encoding="utf-8"
        )
        return run_dir

    @staticmethod
    def _write_manifest(run_dir: Path, manifest: RunManifest) -> None:
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _provenance_fields(provenance: RunProvenance) -> dict[str, object]:
    return {name: getattr(provenance, name) for name in MANIFEST_PROVENANCE_FIELDS}
