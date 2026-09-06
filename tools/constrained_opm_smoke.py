"""Один физический OPM-прогон для первого constrained training label.

Это не финальная оптимизация. Скрипт берёт θ последнего CMA-ES smoke,
строит один командно допустимый план на реальном базовом отклике и прогоняет
его через полный submission-тракт. Полученный ResponseArtifact нужен, чтобы
следующая версия суррогата училась на ограниченной воде, а не экстраполировала
из старого безлимитного датасета.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import argparse
from dataclasses import replace
from pathlib import Path

import conftest
from bridge import submit_schedule
from bridge.opm_deck import OpmDeckEmitter
from bridge.runner import deck_hashes, summary_spec_hash
from config.schema import default_config
from contracts import (
    ArtifactHashes,
    EventKind,
    Theta,
    canonical_bytes,
    hash_schedule,
)
from economics import load_normatives, load_response_artifact
from optimizer.runtime_artifacts import resolve_runtime_artifacts
from optimizer.schedule_search import load_environment, make_evaluator, make_policy
from optimizer.search_run import (
    CONSTRAINTS_PATH,
    LAMBDA,
    MODEL_DIR,
    NORMATIVES,
    OOD_THRESHOLD,
    RESPONSE,
    SEED,
)
from policy.theta import default_theta
from schedule import canonicalize, validate_static
from schedule.canonical import canonical_part_hash
from ui.scenarios import (
    constraints_from_json,
    constraints_to_json,
    load_constraints_file,
)
from ui.artifact_io import _load_schedule

SEARCH_RESULT = Path("data/lambda-window-2007/cmaes.json")
OUT = Path("data/constrained-opm-smoke")


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-response", type=Path, default=RESPONSE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--water-budget-scale", type=float, default=1.0)
    parser.add_argument("--water-reference-response", type=Path)
    parser.add_argument("--freeze-producers-from-zero", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--evaluate-surrogate", action="store_true")
    parser.add_argument(
        "--schedule-json",
        type=Path,
        help="проверить точный сохранённый Schedule, не реконструируя его из θ",
    )
    parser.add_argument(
        "--training-water-scenario-id",
        help="учебный профиль из config/training-water-scenarios.json",
    )
    return parser.parse_args()


def scaled_policy_constraints(constraints, scale: float):
    if not 0.0 <= scale <= 1.0:
        raise ValueError("water-budget-scale должен быть в диапазоне 0..1")
    infrastructure = dict(constraints.infrastructure)
    infrastructure["water_reinjection_fraction"] = (
        float(infrastructure["water_reinjection_fraction"]) * scale
    )
    infrastructure["external_water_m3_per_day"] = (
        float(infrastructure.get("external_water_m3_per_day", 0.0)) * scale
    )
    return replace(constraints, infrastructure=infrastructure)


def build_candidate_schedule(
    env,
    theta: Theta,
    source_response,
    *,
    water_reference=None,
    freeze_producers_from_zero: bool = False,
):
    schedule = make_policy(
        env,
        theta,
        {},
        water_reference_response=water_reference,
    )(source_response)
    if not freeze_producers_from_zero:
        return schedule

    zero_infrastructure = dict(env.constraints.infrastructure)
    zero_infrastructure["water_reinjection_fraction"] = 0.0
    zero_infrastructure["external_water_m3_per_day"] = 0.0
    zero_env = replace(
        env,
        constraints=replace(
            env.constraints, infrastructure=zero_infrastructure
        ),
    )
    zero_schedule = make_policy(zero_env, theta, {})(source_response)
    injection_wells = {
        event.well
        for event in schedule.control_events
        if event.kind is EventKind.SET_RATE
    }
    merged = tuple(
        event
        for event in zero_schedule.control_events
        if event.well not in injection_wells
    ) + tuple(
        event
        for event in schedule.control_events
        if event.well in injection_wells
    )
    return canonicalize(replace(zero_schedule, control_events=merged))


def main() -> int:
    args = _arguments()
    out = args.out
    constraints = load_constraints_file(
        CONSTRAINTS_PATH, require_water_supply=True
    )
    if args.training_water_scenario_id is not None:
        matrix = json.loads(
            Path("config/training-water-scenarios.json").read_text(encoding="utf-8")
        )
        profiles = {item["id"]: item for item in matrix["scenarios"]}
        if args.training_water_scenario_id not in profiles:
            raise ValueError(
                f"неизвестный training water scenario "
                f"{args.training_water_scenario_id!r}"
            )
        document = constraints_to_json(constraints)
        document["infrastructure"] = dict(
            profiles[args.training_water_scenario_id]["infrastructure"]
        )
        constraints = constraints_from_json(document)
        if args.training_water_scenario_id == "unrestricted-extremes":
            raise ValueError(
                "unrestricted-extremes не проходит production OPM smoke: "
                "для него нужен отдельный явно небезопасный генератор датасета"
            )
    constraints_hash = hashlib.sha256(
        canonical_bytes(constraints_to_json(constraints))
    ).hexdigest()
    policy_constraints = scaled_policy_constraints(
        constraints, args.water_budget_scale
    )
    theta = None
    if args.schedule_json is None:
        saved = json.loads(SEARCH_RESULT.read_text(encoding="utf-8"))
        if (
            saved.get("constraints_hash") != constraints_hash
            and args.training_water_scenario_id is None
        ):
            raise ValueError("CMA-ES smoke и OPM smoke используют разные Constraints")
        theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)

    artifacts = resolve_runtime_artifacts()
    env = load_environment(
        model_dir=MODEL_DIR,
        normatives_path=NORMATIVES,
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        lambda_path=LAMBDA,
        ood_threshold=OOD_THRESHOLD,
        constraints=policy_constraints,
    )
    source_response = load_response_artifact(args.source_response)
    water_reference = (
        load_response_artifact(args.water_reference_response)
        if args.water_reference_response is not None
        else None
    )
    schedule = (
        _load_schedule(
            json.loads(args.schedule_json.read_text(encoding="utf-8"))
        )
        if args.schedule_json is not None
        else build_candidate_schedule(
            env,
            theta,
            source_response,
            water_reference=water_reference,
            freeze_producers_from_zero=args.freeze_producers_from_zero,
        )
    )
    static = validate_static(schedule, constraints)
    static.raise_if_violated()
    if args.dry_run:
        predicted_npv = (
            make_evaluator(env)(schedule).npv
            if args.evaluate_surrogate
            else None
        )
        print(
            json.dumps(
                {
                    "canonical_schedule_hash": hash_schedule(schedule),
                    "control_events": len(schedule.control_events),
                    "npv_surrogate": predicted_npv,
                    "static_violations": 0,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    model_dir = conftest.model_z_dir()
    normatives = load_normatives(NORMATIVES)
    emitter = OpmDeckEmitter(model_dir)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        hashes = deck_hashes(deck, schedule)
        summary_hash = summary_spec_hash(deck.summary_plan.spec)
    config = default_config(
        normatives,
        ArtifactHashes(
            deck_hash=hashes.deck_hash,
            history_prefix_hash=canonical_part_hash(schedule.initial_state),
            summary_spec_hash=summary_hash,
            groups_hash=env.groups.group_hash,
            dataset_version_hash=env.model.dataset_hash,
            surrogate_checkpoint_hash=env.model.version,
        ),
        global_seed=SEED,
    )

    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = submit_schedule(
        schedule,
        model_dir,
        out / "work",
        config,
        constraints=constraints,
        oil_density_t_per_m3=env.oil_density_t_per_m3,
        require_water_supply=True,
        groups=env.groups,
        strict=False,
    )
    elapsed = time.monotonic() - started

    (out / "schedule.json").write_bytes(canonical_bytes(schedule))
    if result.response is not None:
        (out / "response.json").write_bytes(canonical_bytes(result.response))
    counts: dict[str, int] = {}
    compensation = []
    if result.dynamic_report is not None:
        for violation in result.dynamic_report.violations:
            counts[violation.kind.value] = counts.get(violation.kind.value, 0) + 1
        compensation = [
            {
                "scope": item.scope,
                "offtake_volume_m3": item.offtake_volume_m3,
                "injection_volume_m3": item.injection_volume_m3,
                "ratio": item.ratio,
            }
            for item in result.dynamic_report.compensation
        ]
    payload = {
        "format": "aios.constrained-opm-smoke.v1",
        "canonical_schedule_hash": hash_schedule(schedule),
        "constraints_hash": constraints_hash,
        "model_version": env.model.version,
        "economic_model_version": getattr(env.npv_head, "version", None),
        "run_id": result.opm_run.run_id,
        "run_status": result.opm_run.status.value,
        "sound": result.sound,
        "elapsed_seconds": elapsed,
        "dynamic_violations_by_kind": counts,
        "compensation": compensation,
        "maximum_field_compensation_from_supply": (
            result.dynamic_report.maximum_field_compensation_from_supply
            if result.dynamic_report is not None
            else None
        ),
        "npv_opm": (
            result.final_npv.npv_methodology
            if result.final_npv is not None
            else None
        ),
        "response_hash": (
            result.response.response_hash if result.response is not None else None
        ),
        "source_response_path": str(args.source_response),
        "source_response_hash": source_response.response_hash,
        "water_budget_scale": args.water_budget_scale,
        "water_reference_response_path": (
            str(args.water_reference_response)
            if args.water_reference_response is not None
            else None
        ),
        "freeze_producers_from_zero": args.freeze_producers_from_zero,
        "schedule_json": str(args.schedule_json) if args.schedule_json else None,
        "training_water_scenario_id": args.training_water_scenario_id,
    }
    (out / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.response is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
