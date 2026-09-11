from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_GLOB = "opm/runs/*/flow.log"
TAIL_BYTES = 65536
REPORT_STEP_PATTERN = re.compile(r"Report step\s+(\d+)/(\d+).*?date = ([^\n]+)")
LOG_DATE_FORMAT = "%d-%b-%Y"
PROGRESS_DATE_FORMAT = "%d.%m.%Y"


def logs_of(directory: Path) -> list[Path]:
    return sorted(directory.glob(LOG_GLOB))


def tail_of(path: Path, limit: int = TAIL_BYTES) -> str:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - limit))
        return stream.read().decode("utf-8", errors="replace")


def progress_of(directory: Path) -> dict[str, Any] | None:
    logs = logs_of(directory)
    if not logs:
        return None
    steps = REPORT_STEP_PATTERN.findall(tail_of(logs[-1]))
    if not steps:
        return None
    step, total, date = steps[-1]
    return {
        "step": int(step),
        "total": int(total),
        "date": datetime.strptime(date.strip(), LOG_DATE_FORMAT).strftime(
            PROGRESS_DATE_FORMAT
        ),
    }


def flow_seconds_of(directory: Path) -> float | None:
    logs = logs_of(directory)
    if not logs:
        return None
    started = min(log.stat().st_ctime for log in logs)
    finished = max(log.stat().st_mtime for log in logs)
    if finished <= started:
        return None
    return round(finished - started, 1)


__all__ = [
    "LOG_GLOB",
    "LOG_DATE_FORMAT",
    "PROGRESS_DATE_FORMAT",
    "REPORT_STEP_PATTERN",
    "TAIL_BYTES",
    "flow_seconds_of",
    "logs_of",
    "progress_of",
    "tail_of",
]
