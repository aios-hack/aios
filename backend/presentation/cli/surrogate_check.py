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

from backend.application.optimization.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
    verify_bundle,
)
from backend.application.cases import load_case
from backend.application.optimization.schedule_search import (
    SELF_REFERENCE_SKIP_REASON,
    LambdaDesyncError,
    SearchEnvironment,
    format_ood_exceedances,
    load_environment,
    make_evaluator,
    missing_invariants,
)
from backend.core.contracts import Constraints, Schedule, hash_schedule
from backend.core.paths import data_root
from backend.domain.connectivity.measure import load_lambda_provenance
from backend.domain.configuration.constraints_io import constraints_hash
from backend.domain.schedule.case_limits import YearlyProduction, apply_case_limits
from backend.domain.schedule.validate_dynamic import (
    FIRST_CONTROL_DECK_DATE_INDEX,
    year_of_step,
)
from backend.infrastructure.resources import model_z_dir, normatives_xlsx
from backend.ml.surrogate.features import ScheduleFeatureizer
from backend.ml.surrogate.physics_checks import check_prediction

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
    "physics_gate=off для базового расписания: базовое расписание и есть опора "
    "прогноза, а дифференциальные инварианты (INJECTION_RESPONSE, "
    "MATERIAL_BALANCE) сравнивают кандидата с опорой — при совпадении все "
    "разности тождественно нулевые, и инвариант ничего не утверждает. Он не "
    "нарушен, он не определён по построению, поэтому гейт снят явно, а не "
    "ошибка спрятана. Одиночные инварианты проверены полностью."
)

CASE_PHYSICS_GATE_NOTE = (
    "physics_gate=off для прогноза на кейсе: проверка обязана дойти до отчёта "
    "и на недопустимом расписании, иначе гейт превращает диагностику в падение. "
    "Все посчитанные инварианты и их нарушения перечислены ниже."
)


def _prediction_block(
    env: SearchEnvironment,
    evaluator: Callable[[Schedule], object],
    schedule: Schedule,
    note: str,
) -> dict:
    result = evaluator(schedule)
    report = getattr(evaluator, "physics_report")
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
            "Проверка production-артефактов и реальный базовый прогноз без OPM"
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
        print(f"строгий режим: {error}", file=sys.stderr)
        return 2
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return exit_code_for(payload)


if __name__ == "__main__":
    raise SystemExit(main())
