from __future__ import annotations

import hashlib
import math
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

from backend.contexts.constraints.domain.config import NormativeSet
from backend.contexts.constraints.domain.schema import default_policies
from backend.contexts.economics.application.base_case import analyze_base_case
from backend.contexts.economics.infrastructure.normatives_io import load_normatives
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.simulation.infrastructure.dataset import DatasetSample
from backend.contexts.surrogate.application.adapter import ResponseAdapter
from backend.contexts.surrogate.application.model import (
    TARGET_NAMES,
    TrainingExample,
    TrajectorySurrogate,
    target_mae,
)
from backend.contexts.surrogate.domain.errors import TrainingCommandError
from backend.contexts.surrogate.domain.metrics import (
    WellTrajectory,
    ranking_metrics,
    state_metrics,
    watercut_metrics,
)
from backend.contexts.surrogate.infrastructure.model_z_context import (
    ModelZFeatureArtifact,
)
from backend.shared.hashing import canonical_bytes


def _evaluation_artifact(
    model_version: str,
    sample: DatasetSample,
    predicted_states: tuple,
    predicted_intervals: tuple,
) -> ResponseArtifact:
    identity = {
        "model_version": model_version,
        "scenario_id": sample.metadata.scenario_id,
        "schedule_hash": sample.metadata.canonical_schedule_hash,
    }
    return ResponseArtifact(
        source_run_id=f"surrogate-evaluation:{model_version[:12]}",
        response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
        state_at_date=predicted_states,
        interval_response=predicted_intervals,
    )


def _trajectories(artifact: ResponseArtifact) -> tuple[WellTrajectory, ...]:
    states: dict[str, list] = {}
    responses: dict[str, list] = {}
    for item in artifact.state_at_date:
        states.setdefault(item.well, []).append(item)
    for item in artifact.interval_response:
        responses.setdefault(item.well, []).append(item)
    if set(states) != set(responses):
        raise TrainingCommandError("the StateAtDate and IntervalResponse axes diverged")
    return tuple(
        WellTrajectory(
            well=well,
            states=tuple(sorted(states[well], key=lambda item: item.deck_date_index)),
            responses=tuple(
                sorted(responses[well], key=lambda item: item.control_step)
            ),
        )
        for well in sorted(states)
    )


def _mean_dict(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        raise TrainingCommandError("an empty list of metrics cannot be averaged")
    return {
        key: mean(float(row[key]) for row in rows)
        for key in rows[0]
        if isinstance(rows[0][key], (int, float)) and not isinstance(rows[0][key], bool)
    }


def evaluate(
    model: TrajectorySurrogate,
    examples: Sequence[TrainingExample],
    samples: Sequence[DatasetSample],
    context: ModelZFeatureArtifact,
    *,
    model_schedule_path: Path,
    normatives_path: Path | None = None,
    normatives: NormativeSet | None = None,
    oil_density_t_per_m3: float,
) -> dict[str, Any]:
    if len(examples) != len(samples) or len(examples) < 2:
        raise TrainingCommandError("ranking requires matching test sets of size >= 2")
    if (normatives_path is None) == (normatives is None):
        raise TrainingCommandError("specify exactly one source of normatives")
    parsed = parse_schedule(model_schedule_path.read_bytes())
    if normatives is None:
        normatives = load_normatives(normatives_path)
    policies = default_policies()
    adapter = ResponseAdapter()
    actual_npv: list[float] = []
    predicted_npv: list[float] = []
    state_rows: list[dict[str, Any]] = []
    watercut_rows: list[dict[str, Any]] = []
    ood_scores: list[float] = []
    ood_exceedances = 0

    for example, sample in zip(examples, samples):
        if sample.response is None:
            raise TrainingCommandError("test sample without a response")
        scored = model.predict(example.input)
        ood_scores.append(scored.ood.score)
        ood_exceedances += len(scored.ood.exceedances)
        states, intervals = adapter.adapt(
            scored.output,
            sample.schedule,
            sample.response,
            context.context.control_dates,
        )
        predicted = _evaluation_artifact(
            model.version, sample, states, intervals
        )
        actual_npv.append(
            analyze_base_case(
                sample.response,
                parsed.dates,
                parsed.t0_deck_date_index,
                normatives,
                policies,
            ).npv_methodology
        )
        predicted_npv.append(
            analyze_base_case(
                predicted,
                parsed.dates,
                parsed.t0_deck_date_index,
                normatives,
                policies,
            ).npv_methodology
        )
        state_rows.append(
            asdict(
                state_metrics(
                    _trajectories(predicted),
                    _trajectories(sample.response),
                    normatives=normatives,
                    policies=policies,
                )
            )
        )
        watercut_rows.append(
            asdict(
                watercut_metrics(
                    sample.response.interval_response,
                    predicted.interval_response,
                    oil_density_t_per_m3=oil_density_t_per_m3,
                )
            )
        )

    finite_ood = [value for value in ood_scores if math.isfinite(value)]
    return {
        "target_mae": target_mae(model, examples),
        "ranking": asdict(ranking_metrics(actual_npv, predicted_npv)),
        "state_mean_per_scenario": _mean_dict(state_rows),
        "watercut_mean_per_scenario": _mean_dict(watercut_rows),
        "ood": {
            "n_scenarios": len(ood_scores),
            "n_scenarios_outside": sum(value > 0.0 for value in ood_scores),
            "n_exceedances": ood_exceedances,
            "max_finite_score": max(finite_ood, default=0.0),
            "n_infinite_scores": sum(not math.isfinite(value) for value in ood_scores),
        },
        "actual_npv_rub": actual_npv,
        "predicted_npv_rub": predicted_npv,
        "synthetic_inputs": False,
    }


def money_rub_per_unit(normatives: NormativeSet) -> tuple[float, ...]:
    linear = {
        "oil_mass_delta": (
            normatives.price_oil_rub_per_t
            - normatives.deductions_rub_per_t
            - normatives.opex_oil_rub_per_t
        ),
        "liquid_volume_delta": -normatives.opex_liquid_rub_per_t,
        "injection_volume_delta": -normatives.opex_injection_rub_per_m3,
    }
    return tuple(float(linear.get(name, 0.0)) for name in TARGET_NAMES)


__all__ = [
    "evaluate",
    "money_rub_per_unit",
]
