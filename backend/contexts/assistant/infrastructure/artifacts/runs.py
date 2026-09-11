from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from backend.contexts.assistant.domain.errors import RunError
from backend.shared.settings import Settings

RUNS_ENV_VAR = "AIOS_JARVIS_RUNS"
OUT_ENV_VAR = "AIOS_OUT_DIR"
MANIFEST_FILE = "manifest.json"
SUBMISSION_DIR = "submission"
CLAIMED_NPV_FILE = "claimed_npv.json"
SCHEDULE_INCLUDE_FILE = "well_schedule.inc"
VALIDATION_DIR = "validation"
VALIDATION_RESULT_FILE = "result.json"
CONSTRAINTS_REPORT_FILE = "constraints_report.json"
NOT_RECORDED = "not-recorded"


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


CLAIMED_NPV_FIELDS: tuple[str, ...] = (
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


def default_runs_root(settings: Settings | None = None) -> Path:
    resolved = Settings.from_env() if settings is None else settings
    if resolved.jarvis_runs is not None:
        return resolved.jarvis_runs
    if resolved.raw.get(OUT_ENV_VAR):
        return resolved.out_root / "runs"
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / "out" / "runs"
    raise RunError(
        "the runs directory was not found: point at it with the environment "
        f"variable {RUNS_ENV_VAR} or run from the repository root that holds out/runs"
    )


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    directory: Path
    manifest: Mapping[str, Any]
    validation: Mapping[str, Any] | None
    constraints_report: Mapping[str, Any] | None
    submission: Mapping[str, Any] | None
    schedule_include: bool

    def field(self, name: str) -> Any:
        if name not in self.manifest:
            return None
        return self.manifest[name]

    def recorded(self, name: str) -> bool:
        return self.manifest.get(name) is not None

    def documents(self) -> tuple[Mapping[str, Any], ...]:
        collected: list[Mapping[str, Any]] = [self.manifest]
        for part in (self.validation, self.constraints_report, self.submission):
            if part is not None:
                collected.append(part)
        return tuple(collected)


def _read_optional_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RunError(
            f"artifact {path} does not parse as JSON: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise RunError(f"artifact {path} is not a JSON object")
    return loaded


class RunStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else default_runs_root()

    @property
    def root(self) -> Path:
        return self._root

    def exists(self) -> bool:
        return self._root.is_dir()

    def run_ids(self) -> tuple[str, ...]:
        if not self._root.is_dir():
            return ()
        found = [
            entry.name
            for entry in self._root.iterdir()
            if entry.is_dir() and (entry / MANIFEST_FILE).is_file()
        ]
        return tuple(sorted(found))

    def latest_run_id(self) -> str | None:
        if not self._root.is_dir():
            return None
        stamped: list[tuple[float, str]] = []
        for name in self.run_ids():
            path = self._root / name / MANIFEST_FILE
            stamped.append((path.stat().st_mtime, name))
        if not stamped:
            return None
        stamped.sort()
        return stamped[-1][1]

    def read(self, run_id: str | None = None) -> RunRecord:
        name = run_id if run_id is not None else self.latest_run_id()
        if name is None:
            raise RunError(
                "the runs directory holds no run with a manifest: "
                f"{self._root}; no calculation has been made yet"
            )
        if Path(name).name != name:
            raise RunError(
                f"run identifier {name!r} is not a directory name"
            )
        directory = self._root / name
        manifest_path = directory / MANIFEST_FILE
        if not manifest_path.is_file():
            known = self.run_ids()
            listed = ", ".join(known) if known else "none"
            raise RunError(
                f"run {name!r} was not found in {self._root}: the manifest "
                f"{manifest_path} is absent; known runs are {listed}"
            )
        manifest = _read_optional_json(manifest_path)
        if manifest is None:
            raise RunError(f"the manifest of run {name!r} cannot be read: {manifest_path}")
        submission_dir = directory / SUBMISSION_DIR
        return RunRecord(
            run_id=name,
            directory=directory,
            manifest=manifest,
            validation=_read_optional_json(
                directory / VALIDATION_DIR / VALIDATION_RESULT_FILE
            ),
            constraints_report=_read_optional_json(
                directory / VALIDATION_DIR / CONSTRAINTS_REPORT_FILE
            ),
            submission=_read_optional_json(submission_dir / CLAIMED_NPV_FILE),
            schedule_include=(submission_dir / SCHEDULE_INCLUDE_FILE).is_file(),
        )
