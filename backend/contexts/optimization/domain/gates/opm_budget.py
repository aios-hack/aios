from __future__ import annotations

RUN_CLOCK: dict[str, object] = {"journal": None, "mark": 0, "started": None}


from backend.contexts.optimization.domain.errors import (
    OpmBudgetError,
)
import json
import os
import time
from dataclasses import (
    dataclass,
)
from pathlib import Path
from typing import (
    Mapping,
)


OPM_BUDGET_JOURNAL = "out/opm-budget.jsonl"


@dataclass(frozen=True, slots=True)
class RunBudget:
    wallclock_seconds: float
    surrogate_evaluations: int
    opm_runs: int
    opm_runs_source: str
    opm_wallclock_seconds: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "wallclock_seconds": self.wallclock_seconds,
            "surrogate_evaluations": self.surrogate_evaluations,
            "opm_runs": self.opm_runs,
            "opm_runs_source": self.opm_runs_source,
            "opm_wallclock_seconds": self.opm_wallclock_seconds,
        }

    def as_provenance(self) -> dict[str, str]:
        return {
            "run_wallclock_seconds": repr(self.wallclock_seconds),
            "run_surrogate_evaluations": str(self.surrogate_evaluations),
            "run_opm_runs": str(self.opm_runs),
            "run_opm_runs_source": self.opm_runs_source,
            "run_opm_wallclock_seconds": (
                "unrecorded"
                if self.opm_wallclock_seconds is None
                else repr(self.opm_wallclock_seconds)
            ),
        }


def _opm_budget_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get("AIOS_OPM_BUDGET_JOURNAL")
    if override is not None and override.strip():
        return Path(override).expanduser()
    root = env.get("AIOS_PROJECT_ROOT")
    return (Path(root) if root else Path.cwd()) / OPM_BUDGET_JOURNAL


def read_opm_budget(
    path: Path, since_line: int = 0
) -> tuple[int, float | None, int]:
    if since_line < 0:
        raise OpmBudgetError(
            f"since_line={since_line} отрицателен: журнал бюджета OPM читается "
            "с начала или с записанной отметки"
        )
    if not path.is_file():
        return 0, None, since_line
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise OpmBudgetError(
            f"журнал бюджета OPM {path} не читается: {error}"
        ) from error
    runs = 0
    seconds = 0.0
    measured = 0
    for number, raw in enumerate(lines):
        if number < since_line or not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except ValueError as error:
            raise OpmBudgetError(
                f"{path}, строка {number + 1}: запись журнала не разбирается — {error}"
            ) from error
        if not isinstance(entry, dict) or "run_id" not in entry:
            raise OpmBudgetError(
                f"{path}, строка {number + 1}: запись без run_id — прогон не опознан"
            )
        runs += 1
        wallclock = entry.get("wallclock_seconds")
        if isinstance(wallclock, (int, float)) and not isinstance(wallclock, bool):
            seconds += float(wallclock)
            measured += 1
    return runs, (seconds if measured else None), len(lines)


def _journal_line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except OSError as error:
        raise OpmBudgetError(
            f"журнал бюджета OPM {path} не читается: {error}"
        ) from error


def start_run_clock() -> None:
    journal = _opm_budget_path()
    RUN_CLOCK["journal"] = journal
    RUN_CLOCK["mark"] = _journal_line_count(journal)
    RUN_CLOCK["started"] = time.monotonic()


def close_run_clock(evaluations: int) -> RunBudget:
    journal = RUN_CLOCK["journal"]
    started = RUN_CLOCK["started"]
    if journal is None or started is None:
        raise OpmBudgetError(
            "учёт бюджета прогона не начат: измерить время и число прогонов OPM "
            "не по чему — вызовите start_run_clock перед поиском"
        )
    return measure_run_budget(
        journal, int(RUN_CLOCK["mark"]), time.monotonic() - started, evaluations
    )


def measure_run_budget(
    journal: Path, mark: int, wallclock: float, evaluations: int
) -> RunBudget:
    opm_runs, opm_seconds, _ = read_opm_budget(journal, mark)
    return RunBudget(
        wallclock_seconds=float(wallclock),
        surrogate_evaluations=int(evaluations),
        opm_runs=int(opm_runs),
        opm_runs_source=str(journal),
        opm_wallclock_seconds=None if opm_seconds is None else float(opm_seconds),
    )


__all__ = [
    "RUN_CLOCK",
    "OPM_BUDGET_JOURNAL",
    "RunBudget",
    "close_run_clock",
    "measure_run_budget",
    "read_opm_budget",
    "start_run_clock",
]
