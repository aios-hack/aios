"""Freeze a cheap ranking and an unranked control BEFORE buying OPM labels.

Only prepares two runs. It never verifies feasibility or promotes a champion.
OOD experimentation is explicit and cannot silently replace the normal gate.
"""
import argparse
import hashlib
import json
import math
import random
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import torch

from backend.application.optimization.runtime_artifacts import resolve_runtime_artifacts
from backend.application.optimization.observed_repair import repair_from_observation
from backend.application.runs import RunRequest, RunWorkflow
from backend.core.contracts import EventKind, canonical_bytes, hash_schedule
from backend.domain.connectivity.groups_artifact import load as load_groups, save as save_groups
from backend.domain.economics import load_response_artifact
from backend.domain.schedule import canonicalize, build_schedule, parse_schedule, validate_static
from backend.infrastructure.opm.opm_deck import render_schedule_include
from backend.infrastructure.resources import model_z_dir
from backend.ml.surrogate.features import ScheduleFeatureizer
from backend.ml.surrogate.model import _features
from backend.ml.surrogate.model_z_context import ModelZFeatureArtifact
from backend.ml.surrogate.npv_block_head import load_direct_npv_head
from backend.ml.surrogate.npv_economic_features import scenario_feature_vector
from backend.ml.surrogate.scenario_ood import ScenarioDensityDomain
from backend.presentation.cli.run import load_run_request, build_provenance


def transfer_fraction(schedule, donor, receiver, fraction):
    """Conserve commanded injection on every date, including low-rate dates."""
    if not 0 < fraction <= 1 or donor == receiver:
        raise ValueError("distinct wells and a fraction in (0,1] required")
    rates = {(e.control_step, e.well): e.value for e in schedule.control_events if e.kind is EventKind.SET_RATE}
    changes = {}
    for (step, well), rate in rates.items():
        if well == donor and (step, receiver) in rates:
            amount = rate * fraction
            changes[(step, donor)] = -amount
            changes[(step, receiver)] = amount
    return canonicalize(replace(schedule, control_events=tuple(
        replace(e, value=e.value + changes.get((e.control_step, e.well), 0))
        if e.kind is EventKind.SET_RATE else e for e in schedule.control_events)))


def choose_pair(rows, seed, allow_ood=False):
    eligible = [r for r in rows if math.isfinite(r["ranking_score"]) and
                math.isfinite(r["ood_score"]) and (r["inside_domain"] or allow_ood)]
    eligible = list({r["schedule_hash"]: r for r in eligible}.values())
    if len(eligible) < 2:
        raise ValueError("At least two eligible candidates required; OOD gate was not relaxed")
    top = max(eligible, key=lambda r: r["ranking_score"])
    control = random.Random(seed).choice([r for r in eligible if r["schedule_hash"] != top["schedule_hash"]])
    return top, control


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--allow-ood-experiment", action="store_true")
    args = parser.parse_args(argv)
    if args.out.exists() or args.count < 6:
        parser.error("new output directory and at least six candidates required")
    started = time.perf_counter()
    torch.set_num_threads(1)
    champion = json.loads((args.campaign / "champion.json").read_text())
    runs = args.campaign / "runs"
    anchor = load_run_request(runs, champion["run_id"])
    if hash_schedule(anchor.schedule) != champion["schedule_hash"]:
        parser.error("anchor schedule differs from champion")
    baseline = load_run_request(runs, "candidate-001")
    measured_path = runs / champion["run_id"] / "response.json"
    observed = load_response_artifact(measured_path)
    grouping = load_groups(runs / champion["run_id"] / "inputs/groups.json")
    artifacts = resolve_runtime_artifacts()
    context = ModelZFeatureArtifact.load(artifacts.feature_context)
    head = load_direct_npv_head(artifacts.npv_head)
    domain = ScenarioDensityDomain.load(artifacts.scenario_ood)
    parsed = parse_schedule((model_z_dir() / "Model_Z_sch.inc").read_bytes())
    dates = parsed.dates[parsed.t0_deck_date_index:]
    if tuple(dates) != tuple(context.context.control_dates):
        parser.error("model and deck horizons differ")
    proposals = [(f"measured-water-{margin}", repair_from_observation(
        anchor.schedule, observed, dates, anchor.constraints, water_margin=margin,
        injection_reference=baseline.schedule)) for margin in (.75, .85, .90, .95, .97, .99)]
    rng = random.Random(args.seed)
    injectors = sorted({e.well for e in anchor.schedule.control_events if e.kind is EventKind.SET_RATE and e.value > 0})
    for _ in range(args.count - 6):
        donor, receiver = rng.sample(injectors, 2)
        fraction = rng.choice((.05, .10, .20))
        proposals.append((f"transfer-{donor}-to-{receiver}-{fraction}",
                          transfer_fraction(anchor.schedule, donor, receiver, fraction)))
    args.out.mkdir(parents=True)
    (args.out / "candidates").mkdir()
    rows, rejected = [], []
    schedules = {}
    featureizer = ScheduleFeatureizer()
    for label, proposal in proposals:
        raw = render_schedule_include(proposal, model_z_dir()).raw
        schedule = build_schedule(parse_schedule(raw), raw)
        digest = hash_schedule(schedule)
        if digest in schedules or digest == champion["schedule_hash"]:
            continue
        if not validate_static(schedule, anchor.constraints).ok:
            rejected.append({"label": label, "reason": "static"})
            continue
        tick = time.perf_counter()
        with torch.inference_mode():
            model_input = featureizer.transform(schedule, context.context)
            x, indices = _features(model_input, head.wells, scenario_context=False)
            vector = scenario_feature_vector(x, indices, n_wells=len(head.wells), feature_set="economic")
            score = head.predict_vector(vector)
            ood = domain.score(vector[:domain.feature_width])
        row = dict(label=label, schedule_hash=digest, ranking_score=score,
                   ood_score=ood, inside_domain=ood <= domain.threshold,
                   inference_seconds=time.perf_counter() - tick)
        rows.append(row)
        schedules[digest] = schedule
        (args.out / "candidates" / f"{digest}.json").write_bytes(canonical_bytes(schedule))
        print(json.dumps(row), flush=True)
    # The file is frozen before any new OPM observation exists.
    selection = []
    reason = None
    try:
        top, control = choose_pair(rows, args.seed, args.allow_ood_experiment)
    except ValueError as error:
        reason = str(error)
    else:
        next_id = max(int(p.name.split("-")[-1]) for p in runs.glob("candidate-*")) + 1
        workflow = RunWorkflow(runs)
        for offset, (arm, row) in enumerate((("model-top", top), ("unranked-control", control))):
            run_id = f"candidate-{next_id + offset:03d}"
            if (runs / run_id).exists():
                raise ValueError("refusing to overwrite a run")
            provenance = build_provenance(SimpleNamespace(provenance={
                "search_strategy": f"experimental-screen-{arm}", "seed": str(args.seed),
                "npv_head_version": head.version}), anchor.constraints)
            workflow.search(RunRequest(run_id, schedules[row["schedule_hash"]], None, anchor.constraints, provenance))
            save_groups(grouping, runs / run_id / "inputs/groups.json")
            selection.append(dict(row, arm=arm, run_id=run_id))
    payload = {"kind": "prospective-screening-experiment", "anchor": champion,
               "anchor_response_sha256": hashlib.sha256(measured_path.read_bytes()).hexdigest(),
               "head_version": head.version, "domain_version": domain.version,
               "domain_threshold": domain.threshold, "seed": args.seed,
               "allow_ood_experiment": args.allow_ood_experiment,
               "rows": rows, "rejected": rejected, "selection": selection,
               "blocked_reason": reason, "screening_seconds": time.perf_counter() - started,
               "warning": "ranking_score is NOT calibrated NPV. OPM required for both arms; no claimed acceleration yet."}
    (args.out / "screening.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"selection": selection, "seconds": payload["screening_seconds"], "blocked": reason}, indent=2))
    return 0 if selection else 2


if __name__ == "__main__":
    raise SystemExit(main())
