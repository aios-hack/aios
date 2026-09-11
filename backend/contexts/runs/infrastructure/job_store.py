from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping, MutableMapping

from backend.shared.i18n.catalog import translate
from backend.shared.json_io import read_json

JOB_FILE = "job.json"
JOB_TEMPORARY_FILE = "job.tmp"
INTERRUPTED_KEY = "runs.status.restarted"
INTERRUPTED_MESSAGE = translate(INTERRUPTED_KEY)


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def job_paths(self, newest_first: bool = False) -> list[Path]:
        return sorted(self.root.glob(f"*/{JOB_FILE}"), reverse=newest_first)

    def read(self, directory: Path) -> dict[str, Any]:
        return dict(read_json(directory / JOB_FILE))

    def write(self, directory: Path, data: Mapping[str, Any]) -> None:
        temporary = directory / JOB_TEMPORARY_FILE
        temporary.write_text(
            json.dumps(dict(data), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(directory / JOB_FILE)

    def recover_interrupted(self) -> int:
        recovered = 0
        for path in self.job_paths():
            data = dict(read_json(path))
            if data.get("status") != "running":
                continue
            data.update(
                status="failed",
                message=INTERRUPTED_MESSAGE,
                message_key=INTERRUPTED_KEY,
            )
            self.write(path.parent, data)
            recovered += 1
        return recovered

    def run_directory(self, run_id: str) -> Path | None:
        directory = (self.root / run_id).resolve()
        if directory.parent != self.root or not directory.is_dir():
            return None
        return directory

    def artifact(self, directory: Path, *parts: str) -> Mapping[str, Any] | None:
        path = directory.joinpath(*parts)
        if not path.is_file():
            return None
        return read_json(path)


__all__ = [
    "INTERRUPTED_KEY",
    "INTERRUPTED_MESSAGE",
    "JOB_FILE",
    "JOB_TEMPORARY_FILE",
    "JobStore",
]
