from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from backend.contexts.economics.application.base_case import load_response_artifact
from backend.contexts.optimization.application import verification_run
from backend.contexts.optimization.application.baseline_search import _peak_step_production
from backend.contexts.optimization.application.environment import (
    load_environment,
    make_evaluator,
)
from backend.contexts.optimization.application.observation_store import persist_observation
from backend.contexts.optimization.application.policy_factory import make_policy
from backend.contexts.optimization.application.search_use_case import (
    FINAL_CAP,
    _repair_predicted_water_balance,
)
from backend.contexts.optimization.domain.errors import (
    ComparisonError,
    VerificationGuardError,
)
from backend.contexts.optimization.infrastructure.artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.contexts.policy.domain.fixed_point import resolve
from backend.contexts.policy.domain.policy import Theta
from backend.contexts.policy.domain.theta import default_theta
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.case_limits import ProductionForecastFn
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.schedule.infrastructure.json_io import load_schedule_json
from backend.shared.hashing import hash_schedule
from backend.shared.json_io import read_json
from backend.shared.resources import chdd_python_dir, model_z_dir


@dataclass(frozen=True, slots=True)
class ComparisonInputs:
    baseline_schedule: Schedule
    control_dates: tuple[date, ...]
    forecast: ProductionForecastFn
    model_dir: Path


def load_comparison_inputs(constraints: Constraints) -> ComparisonInputs:
    try:
        runtime = resolve_runtime_artifacts()
    except Exception as error:
        raise ComparisonError(
            "comparison is impossible: the fast model artifacts are unavailable, "
            f"and without them the production forecast used to project the "
            f"baseline cannot be built — {error}"
        ) from error
    model_dir = model_z_dir()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=verification_run.RESPONSE,
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        scenario_ood_path=runtime.scenario_ood,
        lambda_path=verification_run.LAMBDA,
        constraints=constraints,
        oil_density_t_per_m3=verification_run.OIL_DENSITY_T_PER_M3,
    )
    validate_runtime_economic_head(runtime, env.npv_head)
    return ComparisonInputs(
        baseline_schedule=env.base_schedule,
        control_dates=tuple(env.control_dates),
        forecast=_peak_step_production(env, make_evaluator(env)),
        model_dir=model_dir,
    )


def main() -> int:
    model_dir = model_z_dir()
    normatives_path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    runtime = resolve_runtime_artifacts()
    constraints = verification_run._load_constraints()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=normatives_path,
        response_path=verification_run.RESPONSE,
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        lambda_path=verification_run.LAMBDA,
        constraints=constraints,
        oil_density_t_per_m3=verification_run.OIL_DENSITY_T_PER_M3,
    )
    validate_runtime_economic_head(runtime, env.npv_head)
    initial = load_response_artifact(verification_run.RESPONSE)
    evaluator = make_evaluator(env)

    saved = read_json(Path('data/lambda-window-2007/cmaes.json'))
    if saved.get('schedule_path'):
        schedule = load_schedule_json(Path(saved['schedule_path']))
        repaired_prediction = evaluator(schedule)
        repair_rounds = 0
        actual_hash = hash_schedule(schedule)
        print('Verifying the saved schedule without regenerating the policy.')
    else:
        theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)
        started = time.monotonic()
        final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
        schedule, repaired_prediction, _dynamic, repair_rounds = _repair_predicted_water_balance(
            env, evaluator, final.schedule
        )
        actual_hash = hash_schedule(schedule)
        print(
            f"schedule restored from θ* in {time.monotonic() - started:.1f} s, "
            f"economic head prediction {final.npv / 1e9:.3f} bln, "
            f"policy-stable={final.self_consistent}, water-repair={repair_rounds}",
            flush=True,
        )
    print(f"canonical_schedule_hash: {actual_hash}", flush=True)
    expected = verification_run.EXPECTED_HASH or saved["canonical_schedule_hash"]
    if actual_hash != expected:
        print(f"HASH MISMATCH against the recorded {expected}", flush=True)
        return 3
    print("hash matches the one recorded in cmaes.json", flush=True)

    print("\nlink A: emit, Flow run, response, gate, economics...", flush=True)
    started = time.monotonic()
    try:
        guarded = verification_run.verify_schedule_with_guard(
            schedule,
            verification_run.WORK_ROOT,
            expected_schedule_hash=expected,
            constraints=constraints,
        )
    except VerificationGuardError as error:
        print(f"\n{error}", flush=True)
        return 3
    result = guarded.result
    guard = guarded.guard
    print(f"pipeline finished in {(time.monotonic() - started) / 60:.1f} min", flush=True)

    print(f"\nrun status: {result.opm_run.status}", flush=True)
    print(f"fit for submission (sound): {result.sound}", flush=True)
    for check in result.identities:
        mark = "OK " if check.holds else "NO "
        print(f"  [{mark}] {check.name}", flush=True)
        if not check.holds:
            print(f"        {check.detail}", flush=True)
    if result.dynamic_report is not None:
        counts = {}
        for violation in result.dynamic_report.violations:
            counts[violation.kind] = counts.get(violation.kind, 0) + 1
        print(f"\nvalidate_dynamic: {len(result.dynamic_report.violations)} violations", flush=True)
        for kind, count in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"  {kind}: {count}", flush=True)
    if result.final_npv is not None:
        npv = result.final_npv.npv_methodology
        surrogate_npv = repaired_prediction.npv
        print(
            f"\nNPV from the real run: {npv / 1e9:.3f} bln "
            f"({100.0 * (npv - verification_run.BASE_NPV) / verification_run.BASE_NPV:+.1f}% vs baseline), "
            f"the economic head predicted {surrogate_npv / 1e9:.3f} bln "
            f"(error {100.0 * (surrogate_npv - npv) / npv:+.1f}%)",
            flush=True,
        )
    persist_observation(
        schedule,
        result,
        predicted_npv=repaired_prediction.npv,
        metadata={"candidate": "cmaes-policy", "water_repair_rounds": repair_rounds},
        guard=guard,
    )
    Path("data/g7-result.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": actual_hash,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "failed_identities": [c.name for c in result.failed_identities],
                "npv_surrogate": repaired_prediction.npv,
                "npv_opm": result.final_npv.npv_methodology if result.final_npv else None,
                "npv_baseline": verification_run.BASE_NPV,
                "dynamic_violations": len(result.dynamic_report.violations)
                if result.dynamic_report
                else None,
                "verification_guard": guard.as_dict() if guard is not None else None,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print("\nresult written: data/g7-result.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
