import argparse
import json
import math
import time
from pathlib import Path

import torch

from backend.contexts.optimization.infrastructure.artifacts import resolve_runtime_artifacts
from backend.contexts.reservoir.domain.horizon import HORIZON
from backend.contexts.connectivity.infrastructure.groups_artifact import load as load_groups
from backend.contexts.surrogate.domain.features import ScheduleFeatureizer
from backend.contexts.surrogate.domain.vectorize import build_features
from backend.contexts.surrogate.infrastructure.model_z_context import ModelZFeatureArtifact
from backend.contexts.surrogate.domain.npv_block_head import load_direct_npv_head
from backend.contexts.surrogate.domain.npv_economic_features import scenario_feature_vector
from backend.contexts.robustness.domain.scenario_ood import ScenarioDensityDomain
from backend.interfaces.cli.run import load_run_request
from backend.interfaces.cli.runner import run as run_cli
from backend.shared.json_io import read_json


def ranking_metrics(rows):
    pairs = [(a, b) for i, a in enumerate(rows) for b in rows[i + 1:]
             if abs(a["measured_npv"] - b["measured_npv"]) > 0.01]
    correct = sum((a["predicted_npv"] - b["predicted_npv"]) *
                  (a["measured_npv"] - b["measured_npv"]) > 0 for a, b in pairs)
    if not rows:
        return {"n": 0}
    selected = max(rows, key=lambda r: r["predicted_npv"])
    best = max(rows, key=lambda r: r["measured_npv"])
    return {"n": len(rows), "pairs": len(pairs), "correct_pairs": correct,
            "pairwise_accuracy": correct / len(pairs) if pairs else None,
            "top1_run_id": selected["run_id"], "best_measured_run_id": best["run_id"],
            "top1_regret_rub": best["measured_npv"] - selected["measured_npv"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("output already exists")
    torch.set_num_threads(1)
    started = time.perf_counter()
    artifacts = resolve_runtime_artifacts()
    context = ModelZFeatureArtifact.load(artifacts.feature_context)
    if context.context.control_dates[0] != HORIZON.t0 or len(context.context.control_dates) != HORIZON.n_intervals + 1:
        parser.error("feature context differs from configured horizon")
    head = load_direct_npv_head(artifacts.npv_head)
    domain = ScenarioDensityDomain.load(artifacts.scenario_ood)
    featureizer = ScheduleFeatureizer()
    rows = []
    excluded = []
    conditions = None
    for directory in sorted(args.runs_root.glob("candidate-*")):
        result_path = directory / "economics/result.json"
        if not result_path.is_file():
            continue
        if not (directory / "inputs/groups.json").is_file():
            excluded.append({"run_id": directory.name, "reason": "missing pinned groups artifact"})
            continue
        request = load_run_request(args.runs_root, directory.name)
        result = read_json(result_path)
        manifest = read_json(directory / 'manifest.json')
        current = tuple(manifest.get(k) for k in ("constraints_hash", "deck_hash", "opm_image", "normatives_sha256")) + tuple(
            result.get(k) for k in ("economics_config_hash", "methodology_version_hash")) + (
                load_groups(directory / "inputs/groups.json").group_hash,)
        if None in current or (conditions is not None and conditions != current):
            parser.error("cannot compare runs with missing or different measurement conditions")
        conditions = current
        tick = time.perf_counter()
        with torch.inference_mode():
            model_input = featureizer.transform(request.schedule, context.context)
            x, indices = build_features(model_input, head.wells, scenario_context=False)
            vector = scenario_feature_vector(x, indices, n_wells=len(head.wells), feature_set="economic")
            prediction = head.predict_vector(vector)
            ood = domain.score(vector[:domain.feature_width])
        elapsed = time.perf_counter() - tick
        if not all(math.isfinite(value) for value in (prediction, ood, result["measured_npv"])):
            parser.error("non-finite score or measured label")
        row = dict(run_id=directory.name, predicted_npv=prediction,
                   measured_npv=result["measured_npv"], sound=result["sound"],
                   ood_score=ood, inside_domain=ood <= domain.threshold,
                   inference_seconds=elapsed)
        rows.append(row)
        print(json.dumps(row), flush=True)
    payload = {"kind": "retrospective-not-blind", "head_version": head.version,
               "domain_version": domain.version, "domain_threshold": domain.threshold,
               "rows": rows, "excluded": excluded, "all_runs": ranking_metrics(rows),
               "known_feasible_only_oracle": ranking_metrics([r for r in rows if r["sound"]]),
               "total_seconds": time.perf_counter() - started,
               "warning": "OOD predictions are diagnostics, not approved screening. Feasibility subset uses known OPM labels."}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
