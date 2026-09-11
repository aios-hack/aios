from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable

import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.contexts.optimization.infrastructure.artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
    verify_bundle,
)
from backend.contexts.constraints.application.cases import load_case
from backend.contexts.optimization.application.environment import (
    LambdaDesyncError,
    SELF_REFERENCE_SKIP_REASON,
    SearchEnvironment,
    format_ood_exceedances,
    load_environment,
    make_evaluator,
)
from backend.contexts.optimization.domain.physics_gate import (
    missing_invariants,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.schedule import Schedule
from backend.shared.hashing import hash_schedule
from backend.shared.paths import data_root
from backend.contexts.connectivity.domain.measure import load_lambda_provenance
from backend.contexts.constraints.infrastructure.constraints_io import constraints_hash
from backend.contexts.schedule.domain.case_limits import YearlyProduction, apply_case_limits
from backend.contexts.schedule.domain.validate_dynamic import (
    FIRST_CONTROL_DECK_DATE_INDEX,
    year_of_step,
)
from backend.shared.resources import model_z_dir, normatives_xlsx
from backend.contexts.surrogate.domain.features import ScheduleFeatureizer
from backend.contexts.surrogate.domain.physics_checks import check_prediction
from backend.interfaces.cli.runner import run as run_cli

_LAMBDA_PROVENANCE_KEYS = (
    "artifact_id",
    "measured_at",
    "n_runs",
    "source_run_ids",
    "code_version",
)


def _lambda_artifact_provenance(lambda_path: Path) -> dict[str, str]:
    provenance = load_lambda_provenance(lambda_path)
    record: dict[str, str] = {}
    for name in _LAMBDA_PROVENANCE_KEYS:
        value = getattr(provenance, name)
        if value is None:
            record[f"lambda_artifact_{name}"] = "unrecorded"
        elif isinstance(value, tuple):
            record[f"lambda_artifact_{name}"] = ",".join(value)
        else:
            record[f"lambda_artifact_{name}"] = str(value)
    record["lambda_artifact_provenance_recorded"] = (
        "true" if provenance.is_recorded else "false"
    )
    record["lambda_artifact_missing_fields"] = (
        ",".join(provenance.missing_fields) if provenance.missing_fields else "none"
    )
    return record


BASE_PHYSICS_GATE_NOTE = (
    "physics_gate=off for the base schedule: the base schedule is itself the "
    "reference of the forecast, while the differential invariants (INJECTION_RESPONSE, "
    "MATERIAL_BALANCE) compare a candidate against that reference - when they "
    "coincide every difference is identically zero and the invariant asserts nothing. "
    "It is not violated, it is undefined by construction, so the gate is lifted "
    "explicitly rather than an error being hidden. The single-point invariants are "
    "checked in full."
)

CASE_PHYSICS_GATE_NOTE = (
    "physics_gate=off for the forecast on a case: the check must reach the report "
    "even on an inadmissible schedule, otherwise the gate turns diagnostics into a "
    "crash. Every computed invariant and its violations are listed below."
)


def _prediction_block(
    env: SearchEnvironment,
    evaluator: Callable[[Schedule], object],
    schedule: Schedule,
    note: str,
) -> dict:
    result = evaluator(schedule)
    report = getattr(evaluator, "physics_report", None)
    scored = env.model.predict(
        replace(
            ScheduleFeatureizer().transform(schedule, env.feature_context.context),
            lambda_edges=(),
        )
    )
    return {
        "schedule_hash": hash_schedule(schedule),
        "predicted_npv_rub": result.npv,
        "npv_parts": {name: float(value) for name, value in result.npv_parts.items()},
        "ood_score": result.ood_score,
        "ood_worst": result.ood_worst,
        "ood_exceedances": [dict(item) for item in format_ood_exceedances(scored.ood)],
        "blocking_physics": report.blocking_count,
        "physics_counts": dict(report.counts),
        "physics_complete": report.complete,
        "physics_admissible": report.admissible,
        "physics_gate": "off",
        "physics_gate_note": note,
        "invariants_evaluated": [item.value for item in report.evaluated],
        "invariants_not_checked": list(missing_invariants(report)),
        "invariants_skip_reasons": dict(report.skipped),
        "differential_invariants_checked": not any(
            reason == SELF_REFERENCE_SKIP_REASON for reason in report.skipped.values()
        ),
    }


def _case_schedule(
    env: SearchEnvironment,
    evaluator: Callable[[Schedule], object],
    constraints: Constraints,
) -> Schedule:
    def forecast(schedule: Schedule) -> YearlyProduction:
        response = evaluator(schedule).state.response
        liquid: dict[int, float] = {}
        injection: dict[int, float] = {}
        for state in response.state_at_date:
            step = state.deck_date_index - FIRST_CONTROL_DECK_DATE_INDEX - 1
            if step < 0:
                continue
            year = year_of_step(schedule, step)
            liquid[year] = max(liquid.get(year, 0.0), state.liquid_rate)
            injection[year] = max(injection.get(year, 0.0), state.injection_rate)
        return YearlyProduction(liquid_by_year=liquid, injection_by_year=injection)

    return apply_case_limits(
        env.base_schedule, constraints, env.control_dates, forecast
    )


def check(
    manifest: Path,
    response: Path,
    influence: Path,
    *,
    lambda_strict: bool = False,
    bundle_root: Path | None = None,
    case_path: Path | None = None,
) -> dict:
    artifacts = resolve_runtime_artifacts({"AIOS_SURROGATE_MANIFEST": str(manifest)})
    constraints = Constraints() if case_path is None else load_case(case_path)
    env = load_environment(
        model_dir=model_z_dir(),
        normatives_path=normatives_xlsx(),
        response_path=response,
        lambda_path=influence,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        scenario_ood_path=artifacts.scenario_ood,
        lambda_strict=lambda_strict,
        constraints=constraints,
        physics_gate=False,
    )
    validate_runtime_economic_head(artifacts, env.npv_head)
    evaluator = make_evaluator(env)
    base = _prediction_block(
        env, evaluator, env.base_schedule, BASE_PHYSICS_GATE_NOTE
    )
    payload = {
        "format": "aios.surrogate-runtime-check.v2",
        "status": "ready",
        "trajectory_version": env.model.version,
        "economic_version": env.npv_head.version,
        "dataset_hash": env.model.dataset_hash,
        "scenario_ood_version": env.scenario_ood.version,
        "scenario_ood_threshold": env.scenario_ood.threshold,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "base_predicted_npv_rub": base["predicted_npv_rub"],
        "base_ood_score": base["ood_score"],
        "base_blocking_physics": base["blocking_physics"],
        "base_physics_counts": base["physics_counts"],
        "predictions": {"base": base},
        "case_path": None if case_path is None else str(case_path),
        "opm_executed": False,
        "verified_submission": False,
        "provenance": {
            **dict(env.provenance),
            **_lambda_artifact_provenance(influence),
            "physics_gate": "off",
            "physics_gate_reason": BASE_PHYSICS_GATE_NOTE,
        },
    }
    if case_path is not None:
        projected = _case_schedule(env, evaluator, constraints)
        payload["predictions"]["case"] = _prediction_block(
            env, evaluator, projected, CASE_PHYSICS_GATE_NOTE
        )
        payload["provenance"]["constraints_hash"] = constraints_hash(constraints)
    if bundle_root is not None:
        payload["bundle"] = verify_bundle(bundle_root).as_dict()
    return payload


def exit_code_for(payload: dict) -> int:
    if payload["provenance"].get("lambda_sync") == "desync":
        return 1
    bundle = payload.get("bundle")
    if isinstance(bundle, dict) and bundle.get("status") != "ok":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check the production artifacts and run a real base forecast without OPM"
        )
    )
    parser.add_argument("--manifest", type=Path, default=data_root() / "surrogate-production.json")
    parser.add_argument("--response", type=Path, default=data_root() / "base_case/response.json")
    parser.add_argument("--lambda-path", type=Path, default=data_root() / "lambda-window-2007/lambda.json")
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--lambda-strict", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    torch.set_num_threads(2)
    try:
        payload = check(
            args.manifest,
            args.response,
            args.lambda_path,
            lambda_strict=args.lambda_strict,
            bundle_root=args.bundle_root,
            case_path=args.case,
        )
    except LambdaDesyncError as error:
        print(f"strict mode: {error}", file=sys.stderr)
        return 2
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return exit_code_for(payload)


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
