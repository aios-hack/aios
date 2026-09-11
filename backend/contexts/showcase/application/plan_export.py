
from __future__ import annotations

from backend.contexts.showcase.application.notices import (
    notice_fields,
)

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.contexts.runs.domain.run_artifact import RunArtifact
from backend.contexts.policy.domain.policy import Theta
from backend.shared.hashing import canonical_bytes, hash_schedule
from backend.contexts.economics.application.base_case import (
    analyze_base_case,
    load_response_artifact,
)
from backend.contexts.connectivity.domain.groups import GroupingParams, build_groups
from backend.contexts.connectivity.domain.measure import load_lambda
from backend.contexts.optimization.application.environment import (
    load_environment,
    make_evaluator,
)
from backend.contexts.optimization.application.policy_factory import (
    make_policy,
)
from backend.contexts.optimization.infrastructure.artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.contexts.optimization.application.search_use_case import _repair_predicted_water_balance
from backend.shared.resources import chdd_python_dir, model_z_dir
from backend.contexts.policy.domain.fixed_point import resolve
from backend.contexts.policy.domain.theta import default_theta
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.schedule.domain.validate import validate_static
from backend.contexts.showcase.infrastructure.artifact_io import dump_bundle
from backend.contexts.showcase.application.build_showcase import export_scenario
from backend.contexts.showcase.application.scenarios import (
    ScenarioRobustness,
    constraints_from_json,
    export_scenarios_json,
)

import hashlib
from backend.shared.json_io import read_json

LAMBDA = Path("data/lambda-window-2007/lambda.json")
CMAES = Path("data/lambda-window-2007/cmaes.json")
RESPONSE = Path("data/base_case/response.json")
CONSTRAINTS = Path("config/competition-constraints.json")
OUT = Path("frontend/public/data")
SCENARIO_ID = "policy-plan"
FINAL_CAP = 8


def main() -> int:
    saved = read_json(CMAES)
    base_theta = default_theta()
    theta = Theta(values=dict(saved["theta"]), bounds=base_theta.bounds)

    model_dir = model_z_dir()
    runtime = resolve_runtime_artifacts()
    constraints = constraints_from_json(
        read_json(CONSTRAINTS)
    )
    env = load_environment(
        model_dir=model_dir,
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        lambda_path=LAMBDA,
        constraints=constraints,
    )
    validate_runtime_economic_head(runtime, env.npv_head)
    trace_sink: dict = {}
    initial = load_response_artifact(RESPONSE)
    result = resolve(
        make_policy(env, theta, trace_sink), make_evaluator(env), initial, FINAL_CAP
    )
    schedule, prediction, _dynamic, _repair_rounds = _repair_predicted_water_balance(
        env, make_evaluator(env), result.schedule
    )
    static = validate_static(schedule, constraints)
    if not static.ok:
        raise RuntimeError(static.format())
    actual = hash_schedule(schedule)
    print(f"plan restored: {actual}", flush=True)
    saved_hash = saved["canonical_schedule_hash"]
    hash_matches = actual == saved_hash
    if not hash_matches:
        raise RuntimeError(
            f"hash of the restored plan {actual} differs from the saved {saved_hash}"
        )

    predicted = prediction.state.response
    parsed = parse_schedule((model_dir / "Model_Z_sch.inc").read_bytes())
    analysis = analyze_base_case(
        predicted, parsed.dates, parsed.t0_deck_date_index, env.normatives, env.policies
    )
    influence = load_lambda(LAMBDA)
    groups, _ = build_groups(
        influence, GroupingParams(), extra_wells=schedule.meta.wells
    )
    artifact = RunArtifact(
        config_hash=hashlib.sha256(
            canonical_bytes({"normatives": env.normatives, "policies": env.policies})
        ).hexdigest(),
        schedule=schedule,
        state_at_date=predicted.state_at_date,
        interval_response=predicted.interval_response,
        npv_table=analysis.table,
        trace=trace_sink["trace"].entries if "trace" in trace_sink else (),
        groups=groups,
        lambda_=influence,
        constraints=constraints,
        converged=result.converged,
        self_consistent=result.self_consistent,
        final_npv=None,
    )
    meta = {
        "provenance": "policy-search-candidate",
        "synthetic": False,
        "prediction": True,
        "schedule_reconstructed": True,
        "saved_schedule_hash": saved_hash,
        "canonical_schedule_hash": actual,
        "saved_schedule_hash_matches": hash_matches,
        "lambda_measured": True,
        "source_run_id": f"surrogate-search:{env.model.version[:12]}",
        "response_hash": predicted.response_hash,
        "trajectory_ensemble_version": env.model.version,
        "npv_head_version": env.npv_head.version if env.npv_head else None,
        "predicted_npv_rub": prediction.npv,
        "ood_score": prediction.ood_score,
        "ood_threshold": env.ood_threshold,
        "policy_stable": result.self_consistent,
        **notice_fields(
            "showcase.notice.plan"
            if result.self_consistent
            else "showcase.notice.plan_unstable"
        ),
    }
    written = export_scenario(
        artifact,
        OUT / SCENARIO_ID,
        {kind: dict(meta, kind=kind) for kind in ("timeline", "graph", "npv", "trace")},
    )
    bundle = OUT / "bundles" / f"{SCENARIO_ID}.json"
    dump_bundle(artifact, bundle)
    written.append(bundle)
    index = export_scenarios_json(
        [
            OUT / "bundles" / "base.json",
            OUT / "bundles" / "whatif-injection-cut.json",
            bundle,
        ],
        OUT / "scenarios.json",
        {
            SCENARIO_ID: ScenarioRobustness(
                ood_score=prediction.ood_score,
                ood_threshold=env.ood_threshold,
                predicted_npv_rub=prediction.npv,
            )
        },
    )
    written.append(index)
    for path in written:
        print(path, flush=True)
    print(
        f"\neconomic head NPV: {prediction.npv / 1e9:.3f} bn; "
        f"trajectory-derived NPV: {analysis.npv_methodology / 1e9:.3f} bn; "
        f"OOD={prediction.ood_score}; events {len(schedule.control_events)}, "
        f"self-consistent: {result.self_consistent}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
