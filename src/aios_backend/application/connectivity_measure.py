"""Build the measured λ artifact from cached OPM campaign runs."""

from __future__ import annotations

import os
from pathlib import Path

from aios_backend.core.paths import data_root
from aios_backend.domain.connectivity.campaign import DEFAULT_BATCH_SEEDS, DEFAULT_WINDOW_STEPS, campaign_plan, setup
from aios_backend.domain.connectivity.measure import measure, save_lambda
from aios_backend.domain.economics import load_response_artifact
from aios_backend.infrastructure.opm.dataset import DatasetGenerator
from aios_backend.infrastructure.resources import model_z_dir


def main() -> int:
    try:
        model_z = model_z_dir()
    except FileNotFoundError:
        print("дек Model_Z не найден", flush=True)
        return 2
    root = Path(os.environ.get("AIOS_LAMBDA_ROOT", data_root() / "lambda-window-2007"))
    n_steps = int(os.environ.get("AIOS_LAMBDA_STEPS", str(DEFAULT_WINDOW_STEPS)))
    generator = DatasetGenerator(model_z, root, max_workers=1, timeout_seconds=7200.0)
    prepared = setup(model_z, generator.base_schedule(), n_steps=n_steps)
    report = generator.build(campaign_plan(prepared, seed=DEFAULT_BATCH_SEEDS[0]))
    if report.failed:
        print(f"упавших прогонов {len(report.failed)} — λ не считается", flush=True)
        return 3
    measured = measure(prepared, report.samples, load_response_artifact(data_root() / "base_case" / "response.json"), n_steps=n_steps)
    out = save_lambda(measured, root / "lambda.json")
    print(f"матрица записана: {out}", flush=True)
    return 0
