from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.contexts.runs.infrastructure.job_store import JobStore
from backend.contexts.runs.infrastructure.opm_log_reader import (
    flow_seconds_of,
    progress_of,
)

RUN_LIST_LIMIT = 50
REJECTION_REASON_LIMIT = 5
SIDECAR_ARTIFACTS: tuple[str, ...] = (
    "manifest",
    "constraints",
    "provenance",
    "unseen-result",
)
VALIDATION_ARTIFACT = ("validation", "result.json")
DIAGNOSTICS_ARTIFACT = ("diagnostics.json",)
ECONOMICS_ARTIFACT = ("economics", "result.json")
SUBMISSION_ARTIFACT = ("submission", "claimed_npv.json")
SUBMISSION_SCHEDULE = ("submission", "well_schedule.inc")
VERIFY_MODE = "verify"
RUNNING_STATUS = "running"


def _attach_sidecars(store: JobStore, directory: Path, data: dict[str, Any]) -> None:
    for name in SIDECAR_ARTIFACTS:
        artifact = store.artifact(directory, f"{name}.json")
        if artifact is not None:
            data[name.replace("-", "_")] = artifact
    validation = store.artifact(directory, *VALIDATION_ARTIFACT)
    if validation is not None:
        data["validation"] = validation
    economics = store.artifact(directory, *ECONOMICS_ARTIFACT)
    if economics is not None:
        data["economics"] = economics


def _attach_diagnostics(store: JobStore, directory: Path, data: dict[str, Any]) -> None:
    diagnostics = store.artifact(directory, *DIAGNOSTICS_ARTIFACT)
    if diagnostics is None:
        return
    evaluations = diagnostics.get("evaluations", [])
    data["evaluations"] = len(evaluations)
    data["feasible_evaluations"] = sum(bool(item["feasible"]) for item in evaluations)
    data["rejection_reasons"] = list(
        dict.fromkeys(
            violation["what"]
            for item in evaluations
            for violation in item.get("violations", [])
        )
    )[:REJECTION_REASON_LIMIT]


def _attach_submission(store: JobStore, directory: Path, data: dict[str, Any]) -> None:
    submission = store.artifact(directory, *SUBMISSION_ARTIFACT)
    if submission is None:
        return
    bundle = dict(submission)
    bundle["schedule_present"] = directory.joinpath(*SUBMISSION_SCHEDULE).is_file()
    data["submission"] = bundle


def project_run(store: JobStore, directory: Path, data: dict[str, Any]) -> dict[str, Any]:
    _attach_sidecars(store, directory, data)
    _attach_diagnostics(store, directory, data)
    if data.get("status") == RUNNING_STATUS and data.get("mode") == VERIFY_MODE:
        progress = progress_of(directory)
        if progress is not None:
            data["progress"] = progress
    flow_seconds = flow_seconds_of(directory)
    if flow_seconds is not None:
        data["flow_seconds"] = flow_seconds
    _attach_submission(store, directory, data)
    return data


def project_runs(store: JobStore, limit: int = RUN_LIST_LIMIT) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in store.job_paths(newest_first=True):
        directory = path.parent
        runs.append(project_run(store, directory, store.read(directory)))
    return runs[:limit]


__all__ = [
    "DIAGNOSTICS_ARTIFACT",
    "ECONOMICS_ARTIFACT",
    "REJECTION_REASON_LIMIT",
    "RUNNING_STATUS",
    "RUN_LIST_LIMIT",
    "SIDECAR_ARTIFACTS",
    "SUBMISSION_ARTIFACT",
    "SUBMISSION_SCHEDULE",
    "VALIDATION_ARTIFACT",
    "VERIFY_MODE",
    "project_run",
    "project_runs",
]
