from __future__ import annotations

from typing import Sequence

from backend.contexts.surrogate.domain.crm.types import CrmMetrics, _MIN_TAU
from backend.contexts.surrogate.domain.errors import CrmError


def _filtered(series: Sequence[float], tau: float) -> tuple[float, ...]:
    if tau < _MIN_TAU:
        raise CrmError(f"tau={tau} is too small: the first-order lag degenerates")
    alpha = 1.0 / tau
    if alpha > 1.0:
        alpha = 1.0
    out: list[float] = []
    previous = series[0] if series else 0.0
    for value in series:
        previous = previous + alpha * (value - previous)
        out.append(previous)
    return tuple(out)


def _rank(values: Sequence[float]) -> tuple[float, ...]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1
    return tuple(ranks)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    n = len(left)
    if n < 2:
        return 0.0
    mean_left = sum(left) / n
    mean_right = sum(right) / n
    covariance = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    var_left = sum((a - mean_left) ** 2 for a in left)
    var_right = sum((b - mean_right) ** 2 for b in right)
    if var_left <= 0.0 or var_right <= 0.0:
        return 0.0
    return covariance / (var_left * var_right) ** 0.5


def spearman(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise CrmError("rank correlation requires matching lengths")
    return _pearson(_rank(left), _rank(right))


def _metrics(actual: Sequence[float], predicted: Sequence[float]) -> CrmMetrics:
    n = len(actual)
    if n == 0:
        raise CrmError("metrics are not computed on an empty sample")
    mean_actual = sum(actual) / n
    residual = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    total = sum((a - mean_actual) ** 2 for a in actual)
    r2 = 1.0 - residual / total if total > 0.0 else 0.0
    mae = sum(abs(a - p) for a, p in zip(actual, predicted)) / n
    relative = sorted(
        abs(a - p) / abs(a) for a, p in zip(actual, predicted) if a != 0.0
    )
    if relative:
        middle = len(relative) // 2
        median_relative = (
            relative[middle]
            if len(relative) % 2
            else (relative[middle - 1] + relative[middle]) / 2.0
        )
    else:
        median_relative = 0.0
    return CrmMetrics(
        n_points=n,
        r2=r2,
        mae=mae,
        median_relative_error=median_relative,
        spearman_rank_correlation=spearman(actual, predicted),
    )


__all__ = [
    "spearman",
]
