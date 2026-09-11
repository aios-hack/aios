from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from backend.contexts.simulation.domain.perturbation_design import (
    PerturbationFamily,
    PlanConfig,
    build_plan,
)
from backend.contexts.simulation.infrastructure.dataset import (
    DatasetBuildReport,
    DatasetGenerator,
    DatasetSample,
)
from backend.contexts.surrogate.application.pipeline.state import CycleState, _now
from backend.contexts.surrogate.domain.errors import CycleError
from backend.shared.hashing import canonical_bytes

logger = logging.getLogger("backend.contexts.surrogate.application.pipeline")


def _manifest_status(root: Path) -> tuple[int, int]:
    latest: dict[str, dict[str, Any]] = {}
    try:
        lines = (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0, 0
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        scenario_id = str(row.get("scenario_id", ""))
        if scenario_id:
            latest[scenario_id] = row
    successful = sum(row.get("status") == "OK" for row in latest.values())
    failed = len(latest) - successful
    return successful, failed


def _wait_for_pilot(root: Path, state: CycleState, poll_seconds: int) -> None:
    last = -1
    while True:
        successful, failed = _manifest_status(root)
        if successful != last:
            state.update_stage("pilot-200", completed=successful, failed=failed)
            state.event(
                {
                    "phase": "waiting_pilot",
                    "stage": "pilot-200",
                    "completed": successful,
                    "target": 200,
                    "failed": failed,
                }
            )
            last = successful
        if failed:
            raise CycleError(f"the pilot contains {failed} failed scenarios")
        if successful >= 200:
            return
        time.sleep(poll_seconds)


def _generator(
    model_dir: Path,
    root: Path,
    *,
    workers: int,
) -> DatasetGenerator:
    return DatasetGenerator(
        model_dir,
        root,
        max_workers=workers,
        timeout_seconds=7200.0,
        load_responses=True,
        compact_artifacts=True,
    )


def _build_stage(
    *,
    model_dir: Path,
    root: Path,
    seed: int,
    config: PlanConfig,
    workers: int,
) -> DatasetBuildReport:
    generator = _generator(model_dir, root, workers=workers)
    plan = build_plan(generator.base_schedule(), seed=seed, config=config)
    report = generator.build(plan)
    if report.failed or report.skipped or len(report.samples) != len(plan.specs):
        raise CycleError(
            f"stage {root.name} is incomplete: samples={len(report.samples)}, "
            f"plan={len(plan.specs)}, failed={len(report.failed)}, "
            f"skipped={len(report.skipped)}"
        )
    return report


def _snapshot(
    path: Path,
    report: DatasetBuildReport,
    samples: Sequence[DatasetSample],
    *,
    seed: int,
) -> None:
    payload = {
        "format": "aios.dataset-stage-snapshot.v1",
        "created_at": _now(),
        "dataset_hash": report.dataset_hash,
        "plan_hash": report.plan_hash,
        "seed": seed,
        "n_scenarios": len(samples),
        "families": {
            family.value: sum(item.metadata.family is family for item in samples)
            for family in PerturbationFamily
        },
        "scenarios": [
            {
                "scenario_id": item.metadata.scenario_id,
                "family": item.metadata.family.value,
                "canonical_schedule_hash": item.metadata.canonical_schedule_hash,
                "response_hash": item.metadata.response_hash,
                "run_id": item.metadata.run_id,
                "wallclock_seconds": item.metadata.wallclock_seconds,
            }
            for item in samples
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _combined_hash(pilot: DatasetBuildReport, extra: DatasetBuildReport) -> str:
    payload = {
        "format": "aios.combined-dataset.v1",
        "dataset_hashes": [pilot.dataset_hash, extra.dataset_hash],
        "plan_hashes": [pilot.plan_hash, extra.plan_hash],
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


__all__ = [
    "_build_stage",
    "_combined_hash",
    "_generator",
    "_manifest_status",
    "_snapshot",
    "_wait_for_pilot",
]
