from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.shared.paths import data_root
from backend.contexts.connectivity.application.connectivity_plan import campaign_plan
from backend.contexts.connectivity.application.campaign import (
    DEFAULT_BATCH_SEEDS,
    DEFAULT_WINDOW_STEPS,
    setup,
)
from backend.contexts.connectivity.domain.measure import measure, save_lambda
from backend.domain.economics import load_response_artifact
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
    n_steps = settings.lambda_steps or DEFAULT_WINDOW_STEPS
    generator = DatasetGenerator(model_z, root, max_workers=1, timeout_seconds=7200.0)
    prepared = setup(model_z, generator.base_schedule(), n_steps=n_steps)
    report = generator.build(campaign_plan(prepared, seed=DEFAULT_BATCH_SEEDS[0]))
    if report.failed:
        print(f"упавших прогонов {len(report.failed)} — λ не считается", flush=True)
        return 3
    measured = measure(prepared, report.samples, load_response_artifact(data_root() / "base_case" / "response.json"), n_steps=n_steps)
    out = save_lambda(
        measured,
        root / "lambda.json",
        measured_at=date.today(),
        source_run_ids=sorted({sample.metadata.run_id for sample in report.samples}),
    )
    print(f"матрица записана: {out}", flush=True)
    return 0
