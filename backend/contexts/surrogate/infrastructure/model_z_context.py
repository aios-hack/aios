
from __future__ import annotations

from backend.contexts.surrogate.domain.errors import (
    ModelZContextError,
)

import hashlib
import math
import re
from datetime import date
from pathlib import Path
from statistics import median
from typing import Sequence

import torch

from backend.contexts.simulation.infrastructure.dataset import DatasetSample
from backend.contexts.simulation.infrastructure.well_timeline import build_well_timelines
from backend.contexts.schedule.domain.schedule import N_INTERVALS, Role
from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.shared.hashing import canonical_bytes
from backend.contexts.schedule.domain.build import control_dates as schedule_control_dates
from backend.contexts.schedule.domain.lossless import parse_schedule

from backend.contexts.surrogate.domain.features import (
    FeatureContext,
    history_targets_from_deck,
)
from backend.contexts.surrogate.domain.schedule_roles import build_role_timelines
from backend.contexts.surrogate.domain.model_z_artifact import ModelZFeatureArtifact

_WELSPECS_RE = re.compile(rb"^WELSPECS\b(.*?)^/\s*$", re.MULTILINE | re.DOTALL)
_WELSPECS_ROW_RE = re.compile(
    rb"^\s*'([^']+)'\s+'[^']+'\s+(\d+)\s+(\d+)", re.MULTILINE
)


def _wellheads(raw: bytes, wells: tuple[str, ...]) -> dict[str, dict[str, float]]:
    match = _WELSPECS_RE.search(raw)
    if match is None:
        raise ModelZContextError("Model_Z_sch.inc contains no WELSPECS")
    heads = {
        well.decode("ascii"): (float(i), float(j))
        for well, i, j in _WELSPECS_ROW_RE.findall(match.group(1))
    }
    missing = set(wells) - set(heads)
    if missing:
        raise ModelZContextError(f"WELSPECS has no coordinates for {sorted(missing)}")
    return {
        well: {
            "head_i": heads[well][0],
            "head_j": heads[well][1],
            "numeric_well_id": float(int(well)) if well.isdigit() else float(index),
        }
        for index, well in enumerate(wells)
    }


def _response_maps(sample: DatasetSample):
    if sample.response is None:
        raise ModelZContextError(f"scenario {sample.metadata.scenario_id} has no response")
    interval = {
        (row.well, row.control_step): row for row in sample.response.interval_response
    }
    states = {
        (row.well, row.deck_date_index): row for row in sample.response.state_at_date
    }
    return interval, states


def _axes(samples: Sequence[DatasetSample]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    producers: set[str] = set()
    injectors: set[str] = set()
    for sample in samples:
        timelines = build_role_timelines(sample.schedule)
        for well, timeline in timelines.items():
            for role in timeline.values:
                if role is Role.PROD:
                    producers.add(well)
                elif role is Role.INJ:
                    injectors.add(well)
    return tuple(sorted(producers)), tuple(sorted(injectors))


def _batch_tensors(
    samples: Sequence[DatasetSample],
    producers: tuple[str, ...],
    injectors: tuple[str, ...],
) -> tuple[torch.Tensor, torch.Tensor]:
    injection_rows: list[list[list[float]]] = []
    liquid_rows: list[list[list[float]]] = []
    for sample in samples:
        interval, _ = _response_maps(sample)
        injection_rows.append(
            [
                [interval[(well, step)].injection_volume_delta for well in injectors]
                for step in range(N_INTERVALS)
            ]
        )
        liquid_rows.append(
            [
                [interval[(well, step)].liquid_volume_delta for well in producers]
                for step in range(N_INTERVALS)
            ]
        )
    x = torch.tensor(injection_rows, dtype=torch.float64)
    y = torch.tensor(liquid_rows, dtype=torch.float64)
    x = x - x.mean(dim=0, keepdim=True)
    y = y - y.mean(dim=0, keepdim=True)
    return x.reshape(-1, len(injectors)), y.reshape(-1, len(producers))


def _fit_matrix(x: torch.Tensor, y: torch.Tensor) -> tuple[torch.Tensor, int, float]:
    scale = x.std(dim=0, unbiased=False)
    scale = torch.where(scale > 1e-9, scale, torch.ones_like(scale))
    normalized = x / scale
    gram = normalized.T @ normalized
    ridge = max(1e-9, float(torch.trace(gram)) / max(1, gram.shape[0]) * 1e-4)
    regularized = gram + ridge * torch.eye(gram.shape[0], dtype=gram.dtype)
    weights = torch.linalg.solve(regularized, normalized.T @ y) / scale[:, None]
    weights = weights.clamp_min(0.0).T
    rank = int(torch.linalg.matrix_rank(normalized).item())
    singular = torch.linalg.svdvals(normalized)
    positive = singular[singular > 1e-10]
    condition = (
        float((positive.max() / positive.min()).item())
        if len(positive)
        else math.inf
    )
    return weights, rank, condition


def _correlation(first: torch.Tensor, second: torch.Tensor) -> float:
    left = first.flatten()
    right = second.flatten()
    left = left - left.mean()
    right = right - right.mean()
    denominator = torch.linalg.vector_norm(left) * torch.linalg.vector_norm(right)
    if float(denominator) <= 0.0:
        return 0.0
    return float(torch.dot(left, right) / denominator)


def _achievability(
    samples: Sequence[DatasetSample], injectors: tuple[str, ...]
) -> tuple[dict[str, bool], float]:
    ratios: dict[str, list[float]] = {well: [] for well in injectors}
    target_values: list[float] = []
    for sample in samples:
        _, states = _response_maps(sample)
        timelines = build_well_timelines(sample.schedule)
        role_timelines = build_role_timelines(sample.schedule)
        for well in injectors:
            timeline = timelines[well]
            role_timeline = role_timelines[well]
            for step in range(N_INTERVALS):
                if role_timeline.role(step) is not Role.INJ:
                    continue
                target = timeline.setpoint(step)
                if target <= 0.0:
                    continue
                actual = states[(well, 147 + step)].injection_rate
                ratios[well].append(actual / target)
                target_values.append(target)
    ok = {
        well: bool(values) and median(values) >= 0.9
        for well, values in ratios.items()
    }
    positive = [value for value in target_values if value > 0.0]
    if not positive:
        raise ModelZContextError("the train split has no positive injection targets")
    mean = sum(positive) / len(positive)
    variance = sum((value - mean) ** 2 for value in positive) / len(positive)
    amplitude = variance**0.5 / mean if mean > 0.0 else 0.0
    return ok, amplitude


def estimate_training_lambda(
    samples: Sequence[DatasetSample], control_axis: tuple[date, ...]
) -> Lambda:
    if len(samples) < 8:
        raise ModelZContextError("two independent lambda estimates require at least 8 scenarios")
    producers, injectors = _axes(samples)
    if not producers or not injectors:
        raise ModelZContextError("the train split does not contain both well roles")
    midpoint = len(samples) // 2
    first_x, first_y = _batch_tensors(samples[:midpoint], producers, injectors)
    second_x, second_y = _batch_tensors(samples[midpoint:], producers, injectors)
    first, first_rank, first_condition = _fit_matrix(first_x, first_y)
    second, second_rank, second_condition = _fit_matrix(second_x, second_y)
    pooled = (first + second) / 2.0
    achievability, amplitude = _achievability(samples, injectors)
    return Lambda(
        window_start=control_axis[0],
        window_end=control_axis[-1],
        producers=producers,
        injectors=injectors,
        matrix=tuple(tuple(float(value) for value in row) for row in pooled.tolist()),
        lag_months=0,
        amplitude=amplitude,
        stability=_correlation(first, second),
        rank=min(first_rank, second_rank),
        condition_number=max(first_condition, second_condition),
        achievability_ok=achievability,
    )


def build_model_z_context(
    model_dir: Path | str,
    training_samples: Sequence[DatasetSample],
    *,
    dataset_hash: str,
) -> ModelZFeatureArtifact:
    if not training_samples:
        raise ModelZContextError("the context cannot be built without a train split")
    model_path = Path(model_dir)
    raw = (model_path / "Model_Z_sch.inc").read_bytes()
    parsed = parse_schedule(raw)
    dates = schedule_control_dates(parsed)
    wells = training_samples[0].schedule.meta.wells
    if any(sample.schedule.meta.wells != wells for sample in training_samples):
        raise ModelZContextError("the wells axis diverged between scenarios")
    history_start, history = history_targets_from_deck(raw, wells)
    influence = estimate_training_lambda(training_samples, dates)
    source_payload = {
        "dataset_hash": dataset_hash,
        "responses": sorted(sample.metadata.response_hash for sample in training_samples),
        "schedules": sorted(sample.metadata.canonical_schedule_hash for sample in training_samples),
    }
    source_hash = hashlib.sha256(canonical_bytes(source_payload)).hexdigest()
    return ModelZFeatureArtifact(
        context=FeatureContext(
            control_dates=dates,
            history_start=history_start,
            history_prefix_hash=training_samples[0].schedule.meta.history_prefix_hash,
            history_targets=history,
            static_features=_wellheads(raw, wells),
            lambda_windows=(influence,),
        ),
        dataset_hash=dataset_hash,
        lambda_source_hash=source_hash,
        n_training_scenarios=len(training_samples),
    )
