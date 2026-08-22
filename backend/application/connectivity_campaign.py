"""Executable OPM campaign for measuring reservoir connectivity."""

from __future__ import annotations

import os
import time
from pathlib import Path

from backend.core.paths import data_root
from backend.domain.connectivity.campaign import DEFAULT_BATCH_SEEDS, DEFAULT_WINDOW_STEPS, campaign_plan, setup
from backend.infrastructure.opm.dataset import DatasetGenerator
from backend.infrastructure.resources import model_z_dir


def main() -> int:
    try:
        model_z = model_z_dir()
    except FileNotFoundError:
        print("дек Model_Z не найден", flush=True)
        return 2
    root = Path(os.environ.get("AIOS_LAMBDA_ROOT", data_root() / "lambda-window-2007"))
    workers = int(os.environ.get("AIOS_LAMBDA_WORKERS", "3"))
    limit_text = os.environ.get("AIOS_LAMBDA_LIMIT")
    limit = int(limit_text) if limit_text else None
    n_steps = int(os.environ.get("AIOS_LAMBDA_STEPS", str(DEFAULT_WINDOW_STEPS)))
    generator = DatasetGenerator(model_z, root, max_workers=workers, timeout_seconds=7200.0)
    prepared = setup(model_z, generator.base_schedule(), n_steps=n_steps)
    plan = campaign_plan(prepared, seed=DEFAULT_BATCH_SEEDS[0])
    started = time.monotonic()
    report = generator.build(plan, limit=limit)
    print(f"готово за {(time.monotonic() - started) / 60:.1f} мин: посчитано {report.n_simulated}")
    return 0
