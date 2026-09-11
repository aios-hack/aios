from __future__ import annotations

import time
from pathlib import Path

from backend.shared.paths import data_root
from backend.contexts.connectivity.application.connectivity_plan import campaign_plan
from backend.contexts.connectivity.application.campaign import (
    DEFAULT_BATCH_SEEDS,
    DEFAULT_WINDOW_STEPS,
    setup,
)
from backend.contexts.simulation.infrastructure.dataset import DatasetGenerator
from backend.shared.resources import model_z_dir
from backend.shared.settings import Settings


def main() -> int:
    try:
        model_z = model_z_dir()
    except FileNotFoundError:
        print("дек Model_Z не найден", flush=True)
        return 2
    settings = Settings.from_env()
    root = settings.lambda_root
    workers = settings.lambda_workers
    limit = settings.lambda_limit
    n_steps = settings.lambda_steps or DEFAULT_WINDOW_STEPS
    generator = DatasetGenerator(model_z, root, max_workers=workers, timeout_seconds=7200.0)
    prepared = setup(model_z, generator.base_schedule(), n_steps=n_steps)
    plan = campaign_plan(prepared, seed=DEFAULT_BATCH_SEEDS[0])
    started = time.monotonic()
    report = generator.build(plan, limit=limit)
    print(f"готово за {(time.monotonic() - started) / 60:.1f} мин: посчитано {report.n_simulated}")
    return 0
