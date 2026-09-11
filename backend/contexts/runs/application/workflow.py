from __future__ import annotations

from backend.contexts.runs.domain.errors import (
    SubmissionError,
)

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.runs.domain.run_result import SubmissionBundle
from backend.shared.hashing import canonical_bytes, hash_schedule
from backend.contexts.runs.infrastructure.provenance import git_commit, opm_image
from backend.contexts.reservoir.domain.horizon import HORIZON
from backend.contexts.constraints.infrastructure.constraints_io import (
    constraints_to_json,
)
from backend.contexts.schedule.application.emit import (
    WELLS_SCHEDULE_FILE_NAME,
    verify_schedule_round_trip,
)
from backend.contexts.schedule.infrastructure.json_io import load_schedule_json
from backend.contexts.reservoir.infrastructure.opm_deck import (
    render_control_period_include,
    render_submission_history,
)
from backend.contexts.runs.application.workflow_models import (
    MANIFEST_FIELDS,
    MANIFEST_PROVENANCE_FIELDS,
    SUBMISSION_BUNDLE_FIELDS,
    RunManifest,
    RunProvenance,
    RunRequest,
    SubmissionReport,
    Verification,
    WorkflowStatus,
)
from backend.contexts.runs.application.workflow_records import (
    _bundle_to_json,
    _constraints_report,
    _created_at,
    _provenance_fields,
    _required_text,
)
from backend.shared.json_io import read_json


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
            **_provenance_fields(request.provenance, request.constraints),
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
        fields = _provenance_fields(request.provenance, request.constraints)
        observed_deck_hash = getattr(getattr(result, "opm_run", None), "deck_hash", None)
        if observed_deck_hash:
            fields["deck_hash"] = observed_deck_hash
        manifest = RunManifest(
            run_id=request.run_id,
            status=WorkflowStatus.VERIFIED if sound else WorkflowStatus.REJECTED,
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
        (run_dir / "validation" / "constraints_report.json").write_text(
            json.dumps(
                _constraints_report(
                    getattr(result, "dynamic_report", None),
                    fields.get("constraints_hash"),
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "economics" / "result.json").write_text(
            json.dumps(
                {
                    "npv_methodology": verified_npv,
                    "measured_npv": measured_npv,
                    "sound": sound,
                    "source_run_id": getattr(calculated, "source_run_id", None),
                    "source_response_hash": getattr(calculated, "source_response_hash", None),
                    "economics_config_hash": getattr(calculated, "economics_config_hash", None),
                    "methodology_version_hash": getattr(calculated, "methodology_version_hash", None),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
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

    def submit(self, run_id: str, model_dir: Path) -> SubmissionReport:
        run_dir = self.runs_root / run_id
        if not run_dir.is_dir():
            raise SubmissionError(f"run {run_id!r} not found: {run_dir}")
        manifest = self._read_manifest(run_dir)
        if manifest.sound is not True:
            raise SubmissionError(
                f"the submission bundle cannot be built: run {run_id!r} did not pass "
                f"verification, sound={manifest.sound!r}"
            )
        economics = self._read_economics(run_dir)
        claimed_npv = economics.get("npv_methodology")
        if not isinstance(claimed_npv, (int, float)) or isinstance(claimed_npv, bool):
            raise SubmissionError(
                f"the submission bundle cannot be built: run {run_id!r} has no OPM NPV in "
                f"economics/result.json, there is nothing to claim "
                f"(npv_methodology={claimed_npv!r}); the surrogate forecast is not "
                "substituted for it"
            )
        schedule = self._read_schedule(run_dir)
        emitted = render_control_period_include(schedule, model_dir)
        history = render_submission_history(schedule, model_dir)
        verify_schedule_round_trip(schedule, emitted.raw, history_prefix=history).raise_if_broken()
        submission_dir = run_dir / "submission"
        schedule_path = submission_dir / WELLS_SCHEDULE_FILE_NAME
        bundle = SubmissionBundle(
            canonical_schedule_hash=hash_schedule(schedule),
            content_hash_submission=emitted.content_hash,
            claimed_npv_rub=float(claimed_npv),
            source_run_id=_required_text(
                economics.get("source_run_id"), "source_run_id", run_id
            ),
            response_hash=_required_text(
                economics.get("source_response_hash"), "response_hash", run_id
            ),
            deck_hash=_required_text(manifest.deck_hash, "deck_hash", run_id),
            economics_config_hash=_required_text(
                economics.get("economics_config_hash"), "economics_config_hash", run_id
            ),
            methodology_version_hash=_required_text(
                economics.get("methodology_version_hash"),
                "methodology_version_hash",
                run_id,
            ),
            constraints_hash=_required_text(
                manifest.constraints_hash, "constraints_hash", run_id
            ),
            opm_image=manifest.opm_image or opm_image(),
            git_commit=_required_text(
                manifest.git_commit or git_commit(), "git_commit", run_id
            ),
            created_at=_created_at(submission_dir / "claimed_npv.json"),
        )
        submission_dir.mkdir(parents=True, exist_ok=True)
        schedule_path.write_bytes(emitted.raw)
        (submission_dir / "claimed_npv.json").write_text(
            json.dumps(
                _bundle_to_json(bundle), ensure_ascii=False, indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        self._copy_evidence(run_dir, submission_dir)
        (submission_dir / "validation").mkdir(exist_ok=True)
        (submission_dir / "validation" / "history.inc").write_bytes(history)
        for name in ("horizon.json", "groups.json"):
            source = run_dir / "inputs" / name
            if source.is_file():
                shutil.copy2(source, submission_dir / "validation" / name)
        submitted = RunManifest(
            **{
                **{
                    name: getattr(manifest, name)
                    for name in MANIFEST_FIELDS
                    if name != "status"
                },
                "status": WorkflowStatus.READY_TO_SUBMIT,
            }
        )
        self._write_manifest(run_dir, submitted)
        return SubmissionReport(
            manifest=submitted,
            bundle=bundle,
            directory=submission_dir,
            schedule_path=schedule_path,
        )

    @staticmethod
    def _read_manifest(run_dir: Path) -> RunManifest:
        path = run_dir / "manifest.json"
        if not path.is_file():
            raise SubmissionError(f"run manifest not found: {path}")
        return RunManifest.from_dict(read_json(path))

    @staticmethod
    def _read_economics(run_dir: Path) -> dict[str, object]:
        path = run_dir / "economics" / "result.json"
        if not path.is_file():
            raise SubmissionError(
                f"economics result not found: {path}; the OPM NPV is not claimed "
                "without it"
            )
        document = read_json(path)
        if not isinstance(document, dict):
            raise SubmissionError(f"economics result is not a JSON object: {path}")
        return document

    @staticmethod
    def _read_schedule(run_dir: Path) -> Schedule:
        path = run_dir / "schedule" / "schedule.json"
        if not path.is_file():
            raise SubmissionError(f"run schedule not found: {path}")
        return load_schedule_json(path)

    @staticmethod
    def _copy_evidence(run_dir: Path, submission_dir: Path) -> None:
        validation = run_dir / "validation"
        if validation.is_dir():
            target = submission_dir / "validation"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(validation, target)
        provenance = run_dir / "provenance.json"
        if provenance.is_file():
            shutil.copy2(provenance, submission_dir / "provenance.json")

    def _prepare(self, request: RunRequest) -> Path:
        if not request.run_id or Path(request.run_id).name != request.run_id:
            raise ValueError("run_id must be one plain directory name")
        run_dir = self.runs_root / request.run_id
        for name in ("inputs", "schedule", "prediction", "opm", "validation", "economics", "ui"):
            (run_dir / name).mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs" / "horizon.json").write_text(
            json.dumps(asdict(HORIZON), default=str, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
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
