"""Check production artifacts and run a real baseline prediction without OPM."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from backend.application.optimization.runtime_artifacts import resolve_runtime_artifacts, validate_runtime_economic_head
from backend.application.optimization.schedule_search import load_environment, make_evaluator
from backend.core.paths import data_root
from backend.infrastructure.resources import model_z_dir, normatives_xlsx
from backend.ml.surrogate.physics_checks import check_prediction
from backend.ml.surrogate.features import ScheduleFeatureizer
from dataclasses import replace


def check(manifest: Path, response: Path, influence: Path) -> dict:
    artifacts = resolve_runtime_artifacts({"AIOS_SURROGATE_MANIFEST": str(manifest)})
    env = load_environment(
        model_dir=model_z_dir(), normatives_path=normatives_xlsx(),
        response_path=response, lambda_path=influence,
        checkpoint_path=artifacts.checkpoint, feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head, scenario_ood_path=artifacts.scenario_ood,
    )
    validate_runtime_economic_head(artifacts, env.npv_head)
    result = make_evaluator(env)(env.base_schedule)
    candidate = replace(ScheduleFeatureizer().transform(env.base_schedule, env.feature_context.context), lambda_edges=())
    report = check_prediction(env.model.predict(candidate).output, schedule=env.base_schedule,
                              oil_density_t_per_m3=env.oil_density_t_per_m3)
    return {
        "format": "aios.surrogate-runtime-check.v1", "status": "ready",
        "trajectory_version": env.model.version, "economic_version": env.npv_head.version,
        "dataset_hash": env.model.dataset_hash, "scenario_ood_version": env.scenario_ood.version,
        "scenario_ood_threshold": env.scenario_ood.threshold,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "base_predicted_npv_rub": result.npv, "base_ood_score": result.ood_score,
        "base_blocking_physics": report.blocking_count, "base_physics_counts": dict(report.counts),
        "opm_executed": False, "verified_submission": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=data_root() / "surrogate-production.json")
    parser.add_argument("--response", type=Path, default=data_root() / "base_case/response.json")
    parser.add_argument("--lambda-path", type=Path, default=data_root() / "lambda-window-2007/lambda.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    payload = check(args.manifest, args.response, args.lambda_path)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
