from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import torch

from backend.application.optimization.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
    verify_bundle,
)
from backend.application.optimization.schedule_search import (
    LambdaDesyncError,
    load_environment,
    make_evaluator,
)
from backend.core.paths import data_root
from backend.domain.connectivity.measure import load_lambda_provenance
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


def check(
    manifest: Path,
    response: Path,
    influence: Path,
    *,
    lambda_strict: bool = False,
    bundle_root: Path | None = None,
) -> dict:
    artifacts = resolve_runtime_artifacts({"AIOS_SURROGATE_MANIFEST": str(manifest)})
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
    )
    validate_runtime_economic_head(artifacts, env.npv_head)
    result = make_evaluator(env)(env.base_schedule)
    candidate = replace(
        ScheduleFeatureizer().transform(env.base_schedule, env.feature_context.context),
        lambda_edges=(),
    )
    report = check_prediction(
        env.model.predict(candidate).output,
        schedule=env.base_schedule,
        oil_density_t_per_m3=env.oil_density_t_per_m3,
    )
    payload = {
        "format": "aios.surrogate-runtime-check.v1",
        "status": "ready",
        "trajectory_version": env.model.version,
        "economic_version": env.npv_head.version,
        "dataset_hash": env.model.dataset_hash,
        "scenario_ood_version": env.scenario_ood.version,
        "scenario_ood_threshold": env.scenario_ood.threshold,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "base_predicted_npv_rub": result.npv,
        "base_ood_score": result.ood_score,
        "base_blocking_physics": report.blocking_count,
        "base_physics_counts": dict(report.counts),
        "opm_executed": False,
        "verified_submission": False,
        "provenance": {
            **dict(env.provenance),
            **_lambda_artifact_provenance(influence),
        },
    }
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
