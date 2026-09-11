import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import torch

from backend.contexts.optimization.infrastructure.artifacts import resolve_runtime_artifacts
from backend.domain.economics import load_response_artifact
from backend.contexts.surrogate.application.ensemble import TrajectoryEnsemble
from backend.contexts.surrogate.domain.features import ScheduleFeatureizer
from backend.contexts.surrogate.application.model import (
    TrajectorySurrogate,
    TrainingExample,
    target_mae,
    _legacy_checkpoint_modules,
)
from backend.contexts.surrogate.infrastructure.model_z_context import ModelZFeatureArtifact
from backend.interfaces.cli.run import load_run_request
from backend.interfaces.cli.surrogate.adapt import errors, sample_scenarios
from backend.interfaces.cli.runner import run as run_cli
from backend.shared.json_io import read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--tensors", type=Path, required=True)
    args = parser.parse_args(argv)
    destination = args.experiment / "physical-audit.json"
    if destination.exists():
        parser.error("audit already exists")
    result = read_json(args.experiment / 'result.json')
    torch.set_num_threads(1)
    artifacts = resolve_runtime_artifacts()
    context = ModelZFeatureArtifact.load(artifacts.feature_context)
    production = TrajectoryEnsemble.load(artifacts.checkpoint)
    winner = TrajectorySurrogate.load(args.experiment / result["winner"]["arm"] / "model.pt")
    if winner.version != result["winner"]["model_version"]:
        parser.error("winner checkpoint differs from frozen selection")
    featureizer = ScheduleFeatureizer()
    rows = []
    for run_id in ("candidate-008", "candidate-009"):
        request = load_run_request(args.runs_root, run_id)
        example = TrainingExample(
            replace(featureizer.transform(request.schedule, context.context), lambda_edges=()),
            load_response_artifact(args.runs_root / run_id / "response.json"),
        )
        row = {"run_id": run_id, "split": "validation" if run_id.endswith("008") else "held-out"}
        for name, model in (("production_ensemble", production), ("adapted_winner", winner)):
            began = time.perf_counter()
            row[name] = {"version": model.version, "mae": target_mae(model, [example]),
                         "evaluation_seconds": time.perf_counter() - began}
        rows.append(row)
        print(json.dumps(row), flush=True)
    with _legacy_checkpoint_modules():
        blob = torch.load(args.tensors, mmap=True, weights_only=False)
    if blob["dataset_hash"] != context.dataset_hash or tuple(blob["wells"]) != winner.wells:
        parser.error("historical holdout axes or context differ")
    heldout = sample_scenarios(blob["tensors"]["test"], blob["counts"]["test"],
                               list(range(len(blob["counts"]["test"]))), len(winner.input_scaler.mean))
    parent = production.models[int(result["winner"]["arm"].split("-")[1])]
    historical = {"scenarios": len(blob["counts"]["test"]),
                  "parent_raw_network": errors(parent, heldout),
                  "winner_raw_network": errors(winner, heldout)}
    payload = {"rows": rows, "historical_holdout": historical, "production_changed": False,
               "warning": "Historically inspected labels, not blind. MAE does not certify water constraints, NPV ranking, or global generalization."}
    destination.write_text(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
