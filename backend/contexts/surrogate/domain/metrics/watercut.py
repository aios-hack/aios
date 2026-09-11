from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.contexts.reservoir.domain.response import IntervalResponse, watercut
from backend.contexts.surrogate.domain.errors import MetricsError


@dataclass(frozen=True, slots=True)
class WatercutMetrics:
    n_points: int
    mae: float
    median_absolute_error: float
    share_of_drops: float


def watercut_metrics(
    actual: Sequence[IntervalResponse],
    predicted: Sequence[IntervalResponse],
    *,
    oil_density_t_per_m3: float,
) -> WatercutMetrics:
    if len(actual) != len(predicted):
        raise MetricsError("response series have different lengths")

    errors: list[float] = []
    predicted_series: list[float] = []
    for fact, model in zip(actual, predicted):
        if fact.control_step != model.control_step or fact.well != model.well:
            raise MetricsError(
                f"the pair does not match on the axis: fact ({fact.control_step}, {fact.well}), "
                f"forecast ({model.control_step}, {model.well})"
            )
        if fact.liquid_volume_delta == 0.0 or model.liquid_volume_delta == 0.0:
            continue
        fact_value = watercut(fact, oil_density_t_per_m3)
        model_value = watercut(model, oil_density_t_per_m3)
        errors.append(abs(fact_value - model_value))
        predicted_series.append(model_value)

    if not errors:
        raise MetricsError("watercut is undefined on every interval")

    drops = sum(
        1
        for previous, current in zip(predicted_series, predicted_series[1:])
        if current < previous
    )
    comparisons = max(1, len(predicted_series) - 1)
    ordered = sorted(errors)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2 == 1
        else 0.5 * (ordered[middle - 1] + ordered[middle])
    )

    return WatercutMetrics(
        n_points=len(errors),
        mae=sum(errors) / len(errors),
        median_absolute_error=median,
        share_of_drops=drops / comparisons,
    )


__all__ = [
    "WatercutMetrics",
    "watercut_metrics",
]
