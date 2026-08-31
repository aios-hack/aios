"""Build and verify a no-external-water baseline without throttling production.

This is an active-learning control point, not a submission shortcut: the
organizer's production controls are preserved, injection is projected into
the surrogate-predicted produced-water budget, and the exact resulting
schedule is then run through OPM and the official economics tract.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from backend.core.contracts import EventKind, ResponseArtifact, Schedule, hash_schedule
from backend.domain.economics import load_response_artifact
from backend.domain.schedule import canonicalize, validate_dynamic, validate_static
from backend.infrastructure.resources import chdd_python_dir, model_z_dir
from backend.presentation.ui_export.artifact_io import load_schedule_json

from .runtime_artifacts import resolve_runtime_artifacts, validate_runtime_economic_head
from .schedule_search import (
    SETPOINT_STEP_M3_PER_DAY,
    _interval_produced_water_rate_m3_per_day,
    load_environment,
    make_evaluator,
)
from .verification_run import (
    LAMBDA,
    OIL_DENSITY_T_PER_M3,
    RESPONSE,
    _load_constraints,
    persist_observation,
    verify_schedule,
)

WORK_ROOT = Path("data/water-baseline-submission")
WATER_SAFETY_FACTOR = 0.85


def _project_injection_to_reference_water(
    schedule: Schedule,
    response: ResponseArtifact,
    control_dates,
    *,
    oil_density_t_per_m3: float,
    water_safety_factor: float,
) -> Schedule:
    """Cap commands once against measured baseline produced water.

    Unlike the old iterative repair, this projection cannot multiply a model
    error through repeated floor operations until all injection disappears.
    Production commands remain byte-for-byte semantic equivalents of the
    organizer baseline.
    """

    available = {
        step: water_safety_factor
        * _interval_produced_water_rate_m3_per_day(
            response, step, control_dates, oil_density_t_per_m3
        )
        for step in range(schedule.meta.n_intervals)
    }
    commanded: dict[int, float] = {}
    for event in schedule.control_events:
        if event.kind is EventKind.SET_RATE:
            commanded[event.control_step] = commanded.get(event.control_step, 0.0) + float(
                event.value or 0.0
            )
    factors = {
        step: min(1.0, available[step] / total) if total > 0.0 else 0.0
        for step, total in commanded.items()
    }
    projected_values: dict[tuple[int, str], float] = {}
    projected = []
    for event in schedule.control_events:
        if event.kind is EventKind.SET_RATE:
            value = math.floor(
                float(event.value or 0.0)
                * factors.get(event.control_step, 0.0)
                / SETPOINT_STEP_M3_PER_DAY
            ) * SETPOINT_STEP_M3_PER_DAY
            event = replace(event, value=max(0.0, value))
            projected_values[(event.control_step, event.well)] = float(event.value or 0.0)
        projected.append(event)
    normalized = []
    for event in projected:
        value = projected_values.get((event.control_step, event.well))
        if value is not None and event.kind in (EventKind.OPEN, EventKind.SHUT):
            event = replace(
                event,
                kind=EventKind.OPEN if value > 0.0 else EventKind.SHUT,
            )
        normalized.append(event)
    return canonicalize(
        replace(
            schedule,
            control_events=tuple(normalized),
            meta=replace(schedule.meta, provenance="water-feasible-baseline"),
        )
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--observation",
        type=Path,
        help="previous OPM observation directory used for feedback projection",
    )
    parser.add_argument(
        "--water-safety-factor", type=float, default=WATER_SAFETY_FACTOR
    )
    parser.add_argument(
        "--reseed-injection-from-baseline",
        action="store_true",
        help=(
            "preserve baseline production but re-open injection capacity before "
            "projecting it into an OPM-measured water budget"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not 0.0 < args.water_safety_factor <= 1.0:
        raise ValueError("water-safety-factor должен лежать в (0, 1]")
    runtime = resolve_runtime_artifacts()
    constraints = _load_constraints()
    env = load_environment(
        model_dir=model_z_dir(),
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        lambda_path=LAMBDA,
        constraints=constraints,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )
    validate_runtime_economic_head(runtime, env.npv_head)
    evaluator = make_evaluator(env)

    started = time.monotonic()
    if args.observation is None:
        source_schedule = env.base_schedule
        reference_response = env.real_history
        candidate_name = "water-feasible-baseline"
        work_root = WORK_ROOT
        result_path = Path("data/water-baseline-result.json")
    else:
        source_schedule = (
            env.base_schedule
            if args.reseed_injection_from_baseline
            else load_schedule_json(args.observation / "schedule.json")
        )
        reference_response = load_response_artifact(args.observation / "response.json")
        candidate_name = (
            "opm-water-feedback-reseeded"
            if args.reseed_injection_from_baseline
            else "opm-water-feedback"
        )
        work_root = Path("data/water-feedback-submission")
        result_path = Path("data/water-feedback-result.json")

    schedule = _project_injection_to_reference_water(
        source_schedule,
        reference_response,
        env.control_dates,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
        water_safety_factor=args.water_safety_factor,
    )
    prediction = evaluator(schedule)
    predicted_response = prediction.state.response
    dynamic = validate_dynamic(
        schedule,
        predicted_response.state_at_date,
        predicted_response.interval_response,
        constraints,
        OIL_DENSITY_T_PER_M3,
    )
    repair_rounds = 0
    static = validate_static(schedule, constraints)
    event_counts = Counter(event.kind.value for event in schedule.control_events)
    injection_targets = [
        float(event.value or 0.0)
        for event in schedule.control_events
        if event.kind is EventKind.SET_RATE
    ]
    production_targets = [
        float(event.value or 0.0)
        for event in schedule.control_events
        if event.kind is EventKind.SET_LRAT
    ]
    schedule_hash = hash_schedule(schedule)
    print(
        f"water-baseline построен за {time.monotonic() - started:.1f} с; "
        f"hash={schedule_hash}; head={prediction.npv / 1e9:.3f} млрд; "
        f"repair={repair_rounds}; static={len(static.violations)}; "
        f"dynamic={len(dynamic.violations)}",
        flush=True,
    )
    print(
        f"events={dict(event_counts)}; mean LRAT="
        f"{sum(production_targets) / len(production_targets):.2f}; mean RATE="
        f"{sum(injection_targets) / len(injection_targets):.2f}",
        flush=True,
    )
    if not static.ok:
        raise RuntimeError(f"water-baseline нарушает static: {static.violations[:3]}")

    started = time.monotonic()
    result = verify_schedule(schedule, work_root)
    print(
        f"OPM завершён за {(time.monotonic() - started) / 60:.1f} мин; "
        f"status={result.opm_run.status}; sound={result.sound}; "
        f"NPV={result.final_npv.npv_methodology / 1e9:.3f} млрд"
        if result.final_npv is not None
        else f"OPM завершён: status={result.opm_run.status}, NPV отсутствует",
        flush=True,
    )
    observation_dir = persist_observation(
        schedule,
        result,
        predicted_npv=prediction.npv,
        metadata={
            "candidate": candidate_name,
            "water_repair_rounds": repair_rounds,
            "water_safety_factor": args.water_safety_factor,
            "injection_reseeded_from_baseline": args.reseed_injection_from_baseline,
            "reference_observation": str(args.observation) if args.observation else None,
            "source": "production controls preserved; injection projected from measured water",
        },
    )
    result_path.write_text(
        json.dumps(
            {
                "canonical_schedule_hash": schedule_hash,
                "observation_dir": str(observation_dir),
                "predicted_npv": prediction.npv,
                "opm_npv": (
                    result.final_npv.npv_methodology if result.final_npv else None
                ),
                "sound": result.sound,
                "dynamic_violations": (
                    len(result.dynamic_report.violations)
                    if result.dynamic_report is not None
                    else None
                ),
                "water_repair_rounds": repair_rounds,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
