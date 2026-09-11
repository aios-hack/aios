from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WORKER_MODULE = "backend.presentation.cli.web_run_worker"
WORKER_TIMEOUT_SECONDS = 7200
WORKER_THREAD_LIMIT = "2"


def run_worker(
    directory: Path,
    mode: str,
    budget: int,
    timeout: int = WORKER_TIMEOUT_SECONDS,
) -> int:
    environment = dict(
        os.environ,
        OMP_NUM_THREADS=WORKER_THREAD_LIMIT,
        MKL_NUM_THREADS=WORKER_THREAD_LIMIT,
    )
    command = [
        sys.executable,
        "-m",
        WORKER_MODULE,
        mode,
        "--directory",
        str(directory),
        "--budget",
        str(budget),
    ]
    with (directory / f"{mode}.log").open("w", encoding="utf-8") as log:
        finished = subprocess.run(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
            timeout=timeout,
            check=False,
        )
    return int(finished.returncode)


__all__ = [
    "WORKER_MODULE",
    "WORKER_THREAD_LIMIT",
    "WORKER_TIMEOUT_SECONDS",
    "run_worker",
]
