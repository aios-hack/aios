from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from backend.contexts.constraints.application.cases import load_case
from backend.contexts.optimization.infrastructure.champion import promote_champion
from backend.contexts.optimization.infrastructure.artifacts import (
    resolve_runtime_artifacts,
    resolve_lambda_selection,
    resolve_ood_threshold,
    validate_runtime_economic_head,
)
from backend.contexts.optimization.application.environment import load_environment, make_evaluator
from backend.contexts.optimization.application.search_use_case import (
    _injection_transfer_plan,
    _repair_predicted_water_balance,
    _transfer_injection,
    run_search,
)
from backend.contexts.optimization.application.baseline_search import (
    _peak_step_production,
)
from backend.contexts.optimization.application.verification_run import verify_schedule
from backend.contexts.runs.application.workflow import RunRequest, RunWorkflow
from backend.contexts.schedule.domain.schedule import EventKind
from backend.shared.errors import DomainError
from backend.shared.hashing import hash_schedule
from backend.contexts.reservoir.domain.horizon import HORIZON
from backend.shared.paths import data_root
from backend.contexts.schedule.domain.build import build_schedule
from backend.contexts.schedule.domain.canonical import canonicalize
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.schedule.domain.validate import validate_static
from backend.contexts.schedule.domain.case_limits import apply_case_limits
from backend.contexts.economics.application.base_case import (
    load_response_artifact,
    save_response_artifact,
)
from backend.contexts.optimization.domain.observed_repair import (
    repair_from_observation,
    production_from_observation,
)
from backend.contexts.reservoir.infrastructure.opm_deck import render_schedule_include
from backend.shared.resources import model_z_dir, normatives_xlsx
from backend.interfaces.cli.run import build_provenance, require_docker
from backend.interfaces.cli.selfcheck import check_submission
from backend.interfaces.cli.runner import run as run_cli
from backend.shared.json_io import read_json


def local_candidates(schedule, lambda_, count, seed):
    rng = random.Random(seed)
    yield schedule
    for donor, receiver, volume in _injection_transfer_plan(lambda_, schedule, count // 3):
        yield _transfer_injection(schedule, donor, receiver, volume)
    wells = sorted({e.well for e in schedule.control_events if e.value is not None})
    if not wells:
        return
    for _ in range(count):
        well = rng.choice(wells)
        start = rng.randrange(schedule.meta.n_intervals)
        duration = rng.choice((12, 36, schedule.meta.n_intervals))
        scale = rng.choice((0.85, 0.95, 1.05, 1.15))
        events = tuple(
            replace(e, value=min(500.0, e.value * scale)
                    if e.kind is EventKind.SET_LRAT else e.value * scale)
            if e.well == well and e.value is not None and start <= e.control_step < start + duration
            else e for e in schedule.control_events
        )
        yield canonicalize(replace(schedule, control_events=events))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True, help="new campaign directory")
    parser.add_argument("--evaluations", type=int, default=120)
    parser.add_argument("--opm-budget", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--global-search", action="store_true", help="add CMA-ES in every round")
    parser.add_argument("--resume", action="store_true", help="continue the campaign and use the saved OPM cache")
    parser.add_argument("--direct-only", action="store_true", help="OPM search over measured water without surrogate weights or ranking")
    parser.add_argument("--water-margins", nargs="+", type=float, default=[0.0, 0.85, 0.95],
                        help="fallback probes: 0 means injection shut in, then fractions of the measured available water")
    parser.add_argument("--production-scales", nargs="+", type=float, default=[],
                        help="after the water probes: raise offtake when a pressure margin is measured, for example 1.25")
    args = parser.parse_args(argv)
    if min(args.evaluations, args.opm_budget, args.rounds) < 1:
        parser.error("budgets must be positive")
    if args.direct_only and args.global_search:
        parser.error("--direct-only cannot be combined with --global-search")
    if any(not 0 <= margin < 1 for margin in args.water_margins):
        parser.error("water margins must be in [0,1)")
    import math
    if any(not math.isfinite(scale) or scale <= 1 for scale in args.production_scales):
        parser.error("production scales must be finite and exceed 1")
    if args.root.exists() and not args.resume:
        parser.error("root already exists; use a new campaign directory")
    require_docker()
    constraints = load_case(args.case)
    if args.direct_only:
        from backend.contexts.connectivity.domain.groups import GroupingParams, build_groups
        from backend.contexts.connectivity.domain.measure import load_lambda
        raw = (model_z_dir() / "Model_Z_sch.inc").read_bytes()
        parsed = parse_schedule(raw)
        baseline = build_schedule(parsed, raw)
        selection = resolve_lambda_selection()
        influence = load_lambda(selection.path)
        groups, _ = build_groups(influence, GroupingParams(), extra_wells=baseline.meta.wells)
        artifacts = None
        env = SimpleNamespace(base_schedule=baseline, real_history=None,
                              control_dates=parsed.dates[parsed.t0_deck_date_index:],
                              groups=groups, lambda_=influence, oil_density_t_per_m3=0.9131,
                              model=SimpleNamespace(version=None), npv_head=None, scenario_ood=None)
        evaluator = None
    else:
        artifacts = resolve_runtime_artifacts()
        selection = resolve_lambda_selection(feature_context=artifacts.feature_context)
        env = load_environment(
        model_dir=model_z_dir(), normatives_path=normatives_xlsx(),
        response_path=data_root() / "base_case/response.json",
        checkpoint_path=artifacts.checkpoint, feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head, npv_calibration_path=artifacts.npv_calibration,
        scenario_ood_path=artifacts.scenario_ood, lambda_path=selection.path,
        constraints=constraints, ood_threshold=resolve_ood_threshold().value,
        physics_gate=False,
        )
        validate_runtime_economic_head(artifacts, env.npv_head)
        evaluator = make_evaluator(env)
    args.root.mkdir(parents=True, exist_ok=args.resume)
    if args.resume:
        from backend.contexts.reservoir.domain.horizon import load_horizon
        from backend.contexts.constraints.infrastructure.constraints_io import constraints_hash
        from backend.interfaces.cli.run import load_saved_constraints
        from backend.contexts.connectivity.infrastructure.groups_artifact import load as load_groups
        if load_horizon(str(args.root / "horizon.json")) != HORIZON:
            parser.error("resume horizon differs from the saved campaign")
        for run_dir in (args.root / "runs").glob("candidate-*"):
            saved = load_saved_constraints(run_dir)
            if saved is None or constraints_hash(saved) != constraints_hash(constraints):
                parser.error("resume constraints differ from a saved run")
            groups_path = run_dir / "inputs/groups.json"
            if groups_path.is_file() and load_groups(groups_path).groups != env.groups:
                parser.error("resume groups differ from a saved run")
    (args.root / "horizon.json").write_text(json.dumps({
        "t0": HORIZON.t0.isoformat(), "n_intervals": HORIZON.n_intervals,
        "n_deck_dates": HORIZON.n_deck_dates, "discount_base_year": HORIZON.discount_base_year,
    }, indent=2) + "\n")
    workflow = RunWorkflow(args.root / "runs")
    champion_path = args.root / "champion.json"
    seen = set()
    attempted = 0
    record_path = args.root / "evaluations.json"
    records = read_json(record_path) if args.resume and record_path.is_file() else []
    incumbent = None
    if args.resume:
        recorded_ids = {item.get("run_id") for item in records}
        for directory in sorted((args.root / "runs").glob("candidate-*")):
            economics_path = directory / "economics/result.json"
            manifest_path = directory / "manifest.json"
            if directory.name in recorded_ids or not economics_path.is_file() or not manifest_path.is_file():
                continue
            manifest = read_json(manifest_path)
            if manifest.get("sound") not in (True, False) or manifest.get("status") == "searched":
                continue
            economics = read_json(economics_path)
            item = {"run_id": directory.name, "label": "recovered-completed-run",
                    "schedule_hash": manifest["schedule_hash"], "sound": manifest["sound"],
                    "verified_npv_rub": manifest.get("verified_npv"),
                    "constraints_hash": manifest.get("constraints_hash"), "deck_hash": manifest.get("deck_hash"),
                    "opm_image": manifest.get("opm_image"), "groups_hash": env.groups.group_hash,
                    "economics_config_hash": economics.get("economics_config_hash"),
                    "methodology_version_hash": economics.get("methodology_version_hash")}
            if item["sound"]:
                from backend.contexts.optimization.infrastructure.champion import CONDITION_KEYS
                previous = read_json(champion_path) if champion_path.is_file() else None
                if previous is not None and any(item.get(key) != previous.get(key) for key in CONDITION_KEYS):
                    item["comparison_rejected"] = "isolated run has different or unresolved measurement conditions"
                    records.append(item)
                    continue
                report = workflow.submit(directory.name, model_z_dir())
                if not all(line.passed for line in check_submission(report.directory)):
                    raise RuntimeError("Recovered submission selfcheck failed")
                item["submission"] = str(report.directory.resolve())
                promote_champion(champion_path, item)
            records.append(item)
        record_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        for item in records:
            if item.get("run_id"):
                attempted += 1
                seen.add(item["schedule_hash"])
        if champion_path.is_file():
            from backend.interfaces.cli.run import load_run_request
            champion = read_json(champion_path)
            incumbent = load_run_request(args.root / "runs", champion["run_id"]).schedule

    def record(item):
        records.append(item)
        (args.root / "evaluations.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")

    def verify(candidate, predicted, label):
        nonlocal attempted, incumbent
        digest = hash_schedule(candidate)
        if digest in seen or attempted >= args.opm_budget:
            return
        seen.add(digest)
        static = validate_static(candidate, constraints)
        if not static.ok:
            record({"label": label, "schedule_hash": digest, "stage": "static-rejected", "violations": len(static.violations)})
            return
        attempted += 1
        run_id = f"candidate-{attempted:03d}"
        outcome = SimpleNamespace(provenance={
            "seed": str(args.seed), "search_strategy": label,
            "model_version": env.model.version,
            "npv_head_version": env.npv_head.version if env.npv_head else None,
            "scenario_ood_version": env.scenario_ood.version if env.scenario_ood else None,
            "feature_context_sha256": hashlib.sha256(artifacts.feature_context.read_bytes()).hexdigest() if artifacts else None,
        })
        request = RunRequest(run_id, candidate, predicted, constraints, build_provenance(outcome, constraints))
        workflow.search(request)
        from backend.contexts.connectivity.infrastructure.groups_artifact import (
            build_artifact,
            save as save_groups,
        )
        grouping, _ = build_artifact(env.lambda_, extra_wells=candidate.meta.wells)
        if grouping.groups != env.groups:
            raise RuntimeError("Search and verification groups differ")
        save_groups(grouping, args.root / "runs" / run_id / "inputs/groups.json")
        print(f"OPM {attempted}/{args.opm_budget}: {label}, {digest}", flush=True)
        run_dir = args.root / "runs" / run_id
        def measure(schedule, root):
            result = verify_schedule(schedule, root, constraints=constraints, groups=env.groups)
            if result.response is not None:
                save_response_artifact(result.response, run_dir / "response.json")
            return result
        manifest = workflow.verify(request, measure)
        economics = read_json(run_dir / 'economics/result.json')
        item = {"run_id": run_id, "label": label, "schedule_hash": digest,
                "sound": manifest.sound, "verified_npv_rub": manifest.verified_npv,
                "predicted_npv_rub": predicted, "constraints_hash": manifest.constraints_hash,
                "deck_hash": manifest.deck_hash, "opm_image": manifest.opm_image,
                "groups_hash": env.groups.group_hash,
                "economics_config_hash": economics["economics_config_hash"],
                "methodology_version_hash": economics["methodology_version_hash"]}
        if manifest.sound:
            report = workflow.submit(run_id, model_z_dir())
            if not all(line.passed for line in check_submission(report.directory)):
                raise RuntimeError("submission selfcheck failed")
            item["submission"] = str(report.directory.resolve())
            if promote_champion(champion_path, item):
                incumbent = candidate
                print(f"CHAMPION: {manifest.verified_npv:,.2f} RUB", flush=True)
        record(item)

    def expressible(schedule):
        rendered = render_schedule_include(schedule, model_z_dir())
        return build_schedule(parse_schedule(rendered.raw), rendered.raw)

    baseline = expressible(env.base_schedule)
    verify(baseline, None, "original-baseline")
    projected = (baseline if args.direct_only else
                 apply_case_limits(baseline, constraints, env.control_dates, _peak_step_production(env, evaluator)))
    for round_index in range(args.rounds):
        if attempted >= args.opm_budget:
            break
        anchor = incumbent if incumbent is not None else projected
        candidates = [] if args.direct_only else list(local_candidates(anchor, env.lambda_, args.evaluations, args.seed + round_index))
        if args.global_search:
            outcome = run_search(budget=args.evaluations, case_path=args.case, seed=args.seed + round_index)
            candidates.insert(0, outcome.schedule)
        ranked = {}
        for index, candidate in enumerate(candidates):
            try:
                repaired, evaluation, _, _ = _repair_predicted_water_balance(env, evaluator, candidate)
                repaired = expressible(repaired)
                scored = evaluator(repaired)
                score = scored.npv
                impossible = ("NON_NEGATIVE", "WATERCUT_RANGE", "CUMULATIVE_MONOTONIC", "SHUT_WELL_FLOW")
                if any(scored.physics.get(name, 0) for name in impossible):
                    raise ValueError(f"invalid surrogate output: {scored.physics}")
                digest = hash_schedule(repaired)
                if digest not in seen and validate_static(repaired, constraints).ok:
                    ranked[digest] = (score, repaired)
                    physics = getattr(evaluator, "physics_report", None)
                    record({"round": round_index, "candidate": index, "stage": "surrogate-ranked-not-verified",
                            "schedule_hash": digest, "predicted_npv_rub": score,
                            "physics_counts": dict(scored.physics),
                            "physics_not_checked": dict(physics.skipped) if physics else {},
                            "requires_opm": True})
            except (DomainError, ValueError) as error:
                record({"round": round_index, "candidate": index, "stage": "surrogate-rejected", "reason": str(error)})
            if index % 10 == 0:
                print(f"round {round_index + 1}: scored {index + 1}/{len(candidates)}, eligible {len(ranked)}", flush=True)
        slots = max(1, (args.opm_budget - attempted) // (args.rounds - round_index))
        if not ranked:
            base_response_path = args.root / "base-response.json"
            measured_path = args.root / "runs/candidate-001/response.json"
            observed = (load_response_artifact(measured_path) if measured_path.is_file()
                        else load_response_artifact(base_response_path) if base_response_path.is_file()
                        else env.real_history)
            if observed is None:
                raise RuntimeError("No measured baseline response for direct repair")
            round_stop = min(args.opm_budget, attempted + slots)
            for margin in args.water_margins:
                if attempted >= round_stop:
                    break
                anchor = baseline
                if incumbent is not None and champion_path.is_file():
                    champion = read_json(champion_path)
                    measured = args.root / "runs" / champion["run_id"] / "response.json"
                    if measured.is_file():
                        anchor = incumbent
                        observed = load_response_artifact(measured)
                proposal = repair_from_observation(anchor, observed, env.control_dates, constraints,
                                                  water_margin=margin, density=env.oil_density_t_per_m3,
                                                  injection_reference=baseline)
                verify(expressible(proposal), None, f"observed-water-margin-{margin}")
            for scale in args.production_scales:
                if attempted >= round_stop or incumbent is None:
                    break
                champion = read_json(champion_path)
                observed = load_response_artifact(args.root / "runs" / champion["run_id"] / "response.json")
                proposal = production_from_observation(incumbent, observed, constraints, scale=scale)
                verify(expressible(proposal), None, f"production-headroom-scale-{scale}")
        for score, candidate in sorted(ranked.values(), key=lambda item: item[0], reverse=True)[:slots]:
            verify(candidate, score, f"local-round-{round_index + 1}")
    if not champion_path.exists():
        print("No OPM-verified admissible champion. See evaluations.json.")
        return 2
    print(champion_path.read_text(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
