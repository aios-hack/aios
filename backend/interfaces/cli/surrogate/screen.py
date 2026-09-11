import argparse
import hashlib
import json
import math
import random
import time
from dataclasses import replace
from pathlib import Path

import torch

from backend.contexts.optimization.infrastructure.artifacts import resolve_runtime_artifacts
from backend.contexts.optimization.domain.observed_repair import repair_from_observation
from backend.application.runs import RunRequest, RunWorkflow
from backend.contexts.runs.infrastructure.provenance import git_commit
from backend.core.contracts import EventKind, ResponseArtifact, canonical_bytes, hash_schedule
from backend.contexts.constraints.domain.schema import default_policies
from backend.contexts.connectivity.infrastructure.groups_artifact import (
    load as load_groups,
    save as save_groups,
)
from backend.domain.economics import analyze_base_case, load_normatives, load_response_artifact
from backend.domain.schedule import canonicalize, build_schedule, parse_schedule, validate_static
from backend.contexts.reservoir.infrastructure.opm_deck import render_schedule_include
from backend.shared.resources import model_z_dir, normatives_xlsx
from backend.contexts.surrogate.application.adapter import ResponseAdapter
from backend.contexts.surrogate.domain.features import ScheduleFeatureizer
from backend.contexts.surrogate.application.model import TrajectorySurrogate, _features
from backend.contexts.surrogate.infrastructure.model_z_context import ModelZFeatureArtifact
from backend.contexts.surrogate.domain.npv_block_head import load_direct_npv_head
from backend.contexts.surrogate.domain.npv_economic_features import scenario_feature_vector
from backend.contexts.robustness.domain.scenario_ood import ScenarioDensityDomain
from backend.interfaces.cli.run import load_run_request
from backend.interfaces.cli.runner import run as run_cli
from backend.shared.json_io import read_json


def water_margins(maximum=.95):
    if not math.isfinite(maximum) or not .25 < maximum < 1:
        raise ValueError("maximum water margin must be finite and in (.25,1)")
    return tuple(round(maximum - .25 + .05 * index, 10) for index in range(6))


def known_schedule_hashes(runs, champion):
    known = set()
    for directory in runs.glob("candidate-*"):
        economics = directory / "economics/result.json"
        groups = directory / "inputs/groups.json"
        if not economics.is_file() or not groups.is_file():
            continue
        manifest = read_json(directory / 'manifest.json')
        result = read_json(economics)
        if manifest.get("sound") not in (True, False):
            continue
        if any(manifest.get(k) != champion[k] for k in ("constraints_hash", "deck_hash", "opm_image")):
            continue
        if any(result.get(k) != champion[k] for k in ("economics_config_hash", "methodology_version_hash")):
            continue
        if load_groups(groups).group_hash == champion["groups_hash"]:
            known.add(manifest["schedule_hash"])
    return known


def transfer_fraction(schedule, donor, receiver, fraction):
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


def choose_model_comparison(rows, seed, allow_ood=False):
    eligible = [r for r in rows if all(math.isfinite(r[key]) for key in
                ("ranking_score", "physical_npv", "ood_score")) and
                (r["inside_domain"] or allow_ood)]
    eligible = list({r["schedule_hash"]: r for r in eligible}.values())
    if len(eligible) < 2:
        raise ValueError("At least two eligible candidates required; OOD gate was not relaxed")
    physical = max(eligible, key=lambda row: row["physical_npv"])
    direct = max(eligible, key=lambda row: row["ranking_score"])
    if direct["schedule_hash"] == physical["schedule_hash"]:
        direct = max((row for row in eligible if row["schedule_hash"] != physical["schedule_hash"]),
                     key=lambda row: row["ranking_score"])
    return physical, direct


def add_hybrid_scores(rows):
    if len(rows) < 2:
        raise ValueError("hybrid ranking requires at least two candidates")
    for key in ("ranking_score", "physical_npv"):
        values = [row[key] for row in rows]
        mean = math.fsum(values) / len(values)
        scale = (math.fsum((value - mean) ** 2 for value in values) / len(values)) ** .5
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError(f"hybrid ranking has no finite spread for {key}")
        for row, value in zip(rows, values):
            row[f"{key}_z"] = (value - mean) / scale
    for row in rows:
        row["hybrid_score"] = .5 * (row["ranking_score_z"] + row["physical_npv_z"])
    return rows


def choose_hybrid_comparison(rows, seed, allow_ood=False):
    eligible = [row for row in rows if all(math.isfinite(row[key]) for key in
                ("hybrid_score", "ranking_score", "physical_npv", "ood_score")) and
                (row["inside_domain"] or allow_ood)]
    eligible = list({row["schedule_hash"]: row for row in eligible}.values())
    if len(eligible) < 2:
        raise ValueError("At least two eligible candidates required; OOD gate was not relaxed")
    hybrid = max(eligible, key=lambda row: row["hybrid_score"])
    direct = max(eligible, key=lambda row: row["ranking_score"])
    if direct["schedule_hash"] == hybrid["schedule_hash"]:
        direct = max((row for row in eligible if row["schedule_hash"] != hybrid["schedule_hash"]),
                     key=lambda row: row["ranking_score"])
    return hybrid, direct


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--max-water-margin", type=float, default=.95,
                        help="верхняя доля измеренной воды; >0.95 — явная агрессивная проба, не гарантия допустимости")
    parser.add_argument("--allow-ood-experiment", action="store_true")
    parser.add_argument("--trajectory-model", type=Path,
                        help="research checkpoint: choose its physical-NPV top against direct-head control")
    parser.add_argument("--proposal-family", choices=("all", "water", "transfers"), default="all")
    parser.add_argument("--trajectory-ranking", choices=("physical", "hybrid"), default="physical")
    args = parser.parse_args(argv)
    minimum = 6 if args.proposal_family in {"all", "water"} else 2
    if args.out.exists() or args.count < minimum:
        parser.error(f"new output directory and at least {minimum} candidates required")
    try:
        margins = water_margins(args.max_water_margin)
    except ValueError as error:
        parser.error(str(error))
    started = time.perf_counter()
    torch.set_num_threads(1)
    champion = read_json(args.campaign / 'champion.json')
    runs = args.campaign / "runs"
    known = known_schedule_hashes(runs, champion)
    anchor = load_run_request(runs, champion["run_id"])
    if hash_schedule(anchor.schedule) != champion["schedule_hash"]:
        parser.error("anchor schedule differs from champion")
    if "@sha256:" not in (anchor.provenance.opm_image or ""):
        parser.error("anchor must pin an OPM image digest")
    baseline = load_run_request(runs, "candidate-001")
    measured_path = runs / champion["run_id"] / "response.json"
    observed = load_response_artifact(measured_path)
    grouping = load_groups(runs / champion["run_id"] / "inputs/groups.json")
    artifacts = resolve_runtime_artifacts()
    context = ModelZFeatureArtifact.load(artifacts.feature_context)
    head = load_direct_npv_head(artifacts.npv_head)
    trajectory = TrajectorySurrogate.load(args.trajectory_model) if args.trajectory_model else None
    adapter = ResponseAdapter() if trajectory else None
    normatives = load_normatives(normatives_xlsx()) if trajectory else None
    domain = ScenarioDensityDomain.load(artifacts.scenario_ood)
    parsed = parse_schedule((model_z_dir() / "Model_Z_sch.inc").read_bytes())
    dates = parsed.dates[parsed.t0_deck_date_index:]
    if tuple(dates) != tuple(context.context.control_dates):
        parser.error("model and deck horizons differ")
    proposals = [(f"measured-water-{margin}", repair_from_observation(
        anchor.schedule, observed, dates, anchor.constraints, water_margin=margin,
        injection_reference=baseline.schedule)) for margin in margins] if args.proposal_family != "transfers" else []
    rng = random.Random(args.seed)
    injectors = sorted({e.well for e in anchor.schedule.control_events if e.kind is EventKind.SET_RATE and e.value > 0})
    transfer_count = args.count - len(proposals) if args.proposal_family != "water" else 0
    for _ in range(transfer_count):
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
        if digest in known:
            rejected.append({"label": label, "schedule_hash": digest, "reason": "already measured under identical conditions"})
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
            physical_npv = None
            if trajectory is not None:
                trajectory_input = replace(model_input, lambda_edges=())
                output = trajectory.predict(trajectory_input).output
                states, intervals = adapter.adapt(output, schedule, observed, dates)
                identity = {"model_version": trajectory.version, "schedule_hash": digest}
                response = ResponseArtifact(
                    source_run_id=f"research-surrogate:{trajectory.version[:12]}",
                    response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
                    state_at_date=states, interval_response=intervals)
                physical_npv = analyze_base_case(response, parsed.dates,
                    parsed.t0_deck_date_index, normatives, default_policies()).npv_methodology
        if not math.isfinite(score) or not math.isfinite(ood):
            rejected.append({"label": label, "reason": "non-finite model score"})
            continue
        row = dict(label=label, schedule_hash=digest, ranking_score=score,
                   physical_npv=physical_npv,
                   ood_score=ood, inside_domain=ood <= domain.threshold,
                   inference_seconds=time.perf_counter() - tick)
        rows.append(row)
        schedules[digest] = schedule
        (args.out / "candidates" / f"{digest}.json").write_bytes(canonical_bytes(schedule))
        print(json.dumps(row), flush=True)
    if trajectory is not None and args.trajectory_ranking == "hybrid":
        try:
            add_hybrid_scores(rows)
        except ValueError as error:
            parser.error(str(error))
    selection = []
    reason = None
    try:
        top, control = (choose_hybrid_comparison(rows, args.seed, args.allow_ood_experiment)
                        if trajectory and args.trajectory_ranking == "hybrid" else
                        choose_model_comparison(rows, args.seed, args.allow_ood_experiment)
                        if trajectory else choose_pair(rows, args.seed, args.allow_ood_experiment))
    except ValueError as error:
        reason = str(error)
    else:
        next_id = max(int(p.name.split("-")[-1]) for p in runs.glob("candidate-*")) + 1
        workflow = RunWorkflow(runs)
        primary_arm = "hybrid-top" if args.trajectory_ranking == "hybrid" else "trajectory-top"
        arms = ((primary_arm, top), ("direct-head-control", control)) if trajectory else (
            ("model-top", top), ("unranked-control", control))
        for offset, (arm, row) in enumerate(arms):
            run_id = f"candidate-{next_id + offset:03d}"
            if (runs / run_id).exists():
                raise ValueError("refusing to overwrite a run")
            provenance = replace(anchor.provenance, deck_hash=None, git_commit=git_commit(),
                                 search_strategy=f"experimental-screen-{arm}", seed=str(args.seed),
                                 npv_head_version=head.version,
                                 model_version=trajectory.version if trajectory else anchor.provenance.model_version)
            workflow.search(RunRequest(run_id, schedules[row["schedule_hash"]], None, anchor.constraints, provenance))
            save_groups(grouping, runs / run_id / "inputs/groups.json")
            selection.append(dict(row, arm=arm, run_id=run_id))
    payload = {"kind": "prospective-screening-experiment", "anchor": champion,
               "anchor_response_sha256": hashlib.sha256(measured_path.read_bytes()).hexdigest(),
               "head_version": head.version, "domain_version": domain.version,
               "trajectory_model_version": trajectory.version if trajectory else None,
               "trajectory_ranking": args.trajectory_ranking if trajectory else None,
               "domain_threshold": domain.threshold, "seed": args.seed,
               "allow_ood_experiment": args.allow_ood_experiment,
               "max_water_margin": args.max_water_margin,
               "proposal_family": args.proposal_family,
               "known_measurement_count": len(known),
               "rows": rows, "rejected": rejected, "selection": selection,
               "blocked_reason": reason, "screening_seconds": time.perf_counter() - started,
               "warning": "ranking_score is NOT calibrated NPV. OPM required for both arms; no claimed acceleration yet."}
    (args.out / "screening.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"selection": selection, "seconds": payload["screening_seconds"], "blocked": reason}, indent=2))
    return 0 if selection else 2


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
