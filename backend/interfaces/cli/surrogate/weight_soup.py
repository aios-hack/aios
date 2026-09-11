import argparse
import copy
import json
from dataclasses import replace
from pathlib import Path

import torch

from backend.contexts.optimization.infrastructure.artifacts import resolve_runtime_artifacts
from backend.contexts.economics.application.base_case import load_response_artifact
from backend.contexts.surrogate.domain.features import ScheduleFeatureizer
from backend.contexts.surrogate.application.model import (
    TrajectorySurrogate,
    TrainingExample,
    _example_tensors,
    _legacy_checkpoint_modules,
)
from backend.contexts.surrogate.infrastructure.model_z_context import ModelZFeatureArtifact
from backend.interfaces.cli.run import load_run_request
from backend.interfaces.cli.surrogate.adapt import errors, sample_scenarios
from backend.interfaces.cli.runner import run as run_cli
from backend.shared.json_io import read_json


def interpolate(parent, adapted, alpha):
    model = copy.deepcopy(adapted)
    left, right = parent.network.state_dict(), adapted.network.state_dict()
    model.network.load_state_dict({key: left[key].lerp(right[key], alpha) for key in left})
    model.version = model._fingerprint()
    return model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapted", type=Path, required=True)
    parser.add_argument("--member", type=int, required=True)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-historical-loss-ratio", type=float, default=1.01)
    parser.add_argument("--selection-run", default="candidate-008")
    parser.add_argument("--audit-run", default="candidate-009")
    parser.add_argument("--alphas", type=float, nargs="+", default=[.125, .25, .375, .5, .625, .75, .875, 1.])
    args = parser.parse_args(argv)
    if args.out.exists() or not 1 <= args.max_historical_loss_ratio < 2:
        parser.error("new output directory and historical ratio in [1,2) required")
    if not args.alphas or any(not 0 < alpha <= 1 for alpha in args.alphas):
        parser.error("alphas must be in (0,1]")
    torch.set_num_threads(10)
    artifacts = resolve_runtime_artifacts()
    manifest = read_json(artifacts.checkpoint)
    members = [(artifacts.checkpoint.parent / path).resolve() for path in manifest["members"]]
    if not 0 <= args.member < len(members):
        parser.error("unknown member")
    parent, adapted = TrajectorySurrogate.load(members[args.member]), TrajectorySurrogate.load(args.adapted)
    if parent.wells != adapted.wells or parent.network.state_dict().keys() != adapted.network.state_dict().keys():
        parser.error("models are not interpolation-compatible")
    context = ModelZFeatureArtifact.load(artifacts.feature_context)
    with _legacy_checkpoint_modules():
        blob = torch.load(args.tensors, mmap=True, weights_only=False)
    historical = sample_scenarios(blob["tensors"]["test"], blob["counts"]["test"],
                                  list(range(len(blob["counts"]["test"]))), len(parent.input_scaler.mean))
    featureizer, local = ScheduleFeatureizer(), {}
    if args.selection_run == args.audit_run:
        parser.error("selection and audit runs must differ")
    for run_id in (args.selection_run, args.audit_run):
        request = load_run_request(args.runs_root, run_id)
        model_input = replace(featureizer.transform(request.schedule, context.context), lambda_edges=())
        response = load_response_artifact(args.runs_root / run_id / "response.json")
        local[run_id] = _example_tensors([TrainingExample(model_input, response)], parent.wells)
    parent_historical = errors(parent, historical)
    rows = []
    for alpha in sorted(set(args.alphas)):
        model = interpolate(parent, adapted, alpha)
        row = {"alpha": alpha, "version": model.version, "historical": errors(model, historical),
               "selection": {"run_id": args.selection_run, **errors(model, local[args.selection_run])},
               "audit": {"run_id": args.audit_run, **errors(model, local[args.audit_run])}}
        row["historical_loss_ratio"] = row["historical"]["loss"] / parent_historical["loss"]
        rows.append(row)
        print(json.dumps(row), flush=True)
    eligible = [row for row in rows if row["historical_loss_ratio"] <= args.max_historical_loss_ratio]
    winner = min(eligible, key=lambda row: row["selection"]["loss"]) if eligible else None
    args.out.mkdir(parents=True)
    payload = {"parent_historical": parent_historical, "rows": rows, "winner": winner,
               "selection_rule": "lowest configured selection-run loss within historical loss ratio bound",
               "production_changed": False}
    (args.out / "result.json").write_text(json.dumps(payload, indent=2) + "\n")
    if winner:
        interpolate(parent, adapted, winner["alpha"]).save(args.out / "research-model.pt")
    return 0 if winner else 2


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
