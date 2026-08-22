"""Persist one plan evaluation as a complete, inspectable run directory.

The workflow deliberately accepts the OPM step as a callable.  Application
code owns the sequence and files; infrastructure owns how OPM is launched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from backend.core.contracts import Schedule, canonical_bytes, hash_schedule


class WorkflowStatus(Enum):
    SEARCHED = "searched"
    VERIFIED = "verified"
    REJECTED = "rejected"
    READY_TO_SUBMIT = "ready_to_submit"


class Verification(Protocol):
    sound: bool
    npv_methodology: float | None


@dataclass(frozen=True, slots=True)
class RunRequest:
    """A plan produced by the fast model, ready for an independent check."""

    run_id: str
    schedule: Schedule
    predicted_npv: float | None = None


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    status: WorkflowStatus
    schedule_hash: str
    predicted_npv: float | None
    verified_npv: float | None
    sound: bool | None

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "schedule_hash": self.schedule_hash,
            "predicted_npv": self.predicted_npv,
            "verified_npv": self.verified_npv,
            "sound": self.sound,
        }


class RunWorkflow:
    """Writes the fixed run layout and advances it from search to OPM result."""

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
        )
        self._write_manifest(run_dir, manifest)
        return manifest

    def verify(
        self, request: RunRequest, verify: Callable[[Schedule, Path], Verification]
    ) -> RunManifest:
        run_dir = self._prepare(request)
        result = verify(request.schedule, run_dir / "opm")
        sound = result.sound
        manifest = RunManifest(
            run_id=request.run_id,
            status=WorkflowStatus.READY_TO_SUBMIT if sound else WorkflowStatus.REJECTED,
            schedule_hash=hash_schedule(request.schedule),
            predicted_npv=request.predicted_npv,
            verified_npv=result.npv_methodology,
            sound=sound,
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
                    "failed_identities": [item.name for item in getattr(result, "failed_identities", ())],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "economics" / "result.json").write_text(
            json.dumps({"npv_methodology": result.npv_methodology}, indent=2) + "\n",
            encoding="utf-8",
        )
        self._write_manifest(run_dir, manifest)
        return manifest

    def full(
        self,
        search: Callable[[], RunRequest],
        verify: Callable[[Schedule, Path], Verification],
    ) -> RunManifest:
        """Run search once, then verify the exact returned schedule once."""
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
