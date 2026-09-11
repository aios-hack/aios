from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from backend.contexts.reservoir.domain.response import IntervalResponse
from backend.contexts.schedule.domain.schedule import N_INTERVALS

from backend.contexts.surrogate.domain.crm.statistics import _filtered, _metrics
from backend.contexts.surrogate.domain.crm.types import (
    CrmEvaluation,
    CrmMetrics,
    CrmModel,
    CrmSplit,
    DEFAULT_RIDGE,
    DEFAULT_TAU_INTERVALS,
    DEFAULT_TRAIN_FRACTION,
    _CONVERGENCE_TOLERANCE,
    _MAX_SWEEPS,
    _MIN_TAU,
)
from backend.contexts.surrogate.domain.errors import CrmError


def _series_by_well(
    interval_response: Iterable[IntervalResponse], n_intervals: int
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    liquid: dict[str, list[float]] = {}
    injection: dict[str, list[float]] = {}
    seen: set[tuple[int, str]] = set()
    for row in interval_response:
        if row.control_step >= n_intervals:
            continue
        key = (row.control_step, row.well)
        if key in seen:
            raise CrmError(
                f"duplicate IntervalResponse at (control_step={row.control_step}, "
                f"well={row.well!r})"
            )
        seen.add(key)
        liquid.setdefault(row.well, [0.0] * n_intervals)[row.control_step] = (
            row.liquid_volume_delta
        )
        injection.setdefault(row.well, [0.0] * n_intervals)[row.control_step] = (
            row.injection_volume_delta
        )
    if not liquid:
        raise CrmError("IntervalResponse is empty: there is nothing to build the baseline on")
    return liquid, injection


class CrmBaseline:
    def __init__(
        self,
        *,
        tau_intervals: float = DEFAULT_TAU_INTERVALS,
        ridge: float = DEFAULT_RIDGE,
        enforce_material_balance: bool = True,
    ) -> None:
        if tau_intervals < _MIN_TAU:
            raise CrmError(f"tau_intervals={tau_intervals} is too small")
        if ridge < 0.0:
            raise CrmError(f"ridge={ridge} is negative")
        self.tau_intervals = tau_intervals
        self.ridge = ridge
        self.enforce_material_balance = enforce_material_balance

    def fit(
        self,
        interval_response: Iterable[IntervalResponse],
        *,
        train_intervals: int | None = None,
        n_intervals: int = N_INTERVALS,
    ) -> CrmEvaluation:
        liquid, injection = _series_by_well(interval_response, n_intervals)
        if train_intervals is None:
            train_intervals = int(n_intervals * DEFAULT_TRAIN_FRACTION)
        split = CrmSplit(train_intervals=train_intervals, n_intervals=n_intervals)

        producers = tuple(
            well
            for well in sorted(liquid)
            if all(liquid[well][k] > 0.0 for k in range(n_intervals))
        )
        if not producers:
            raise CrmError(
                "there is no producer operating across all intervals: an honest "
                "split over time is impossible"
            )
        injectors = tuple(
            well
            for well in sorted(injection)
            if sum(injection[well][k] for k in split.train_steps) > 0.0
        )
        if not injectors:
            raise CrmError("there is no injector with injection on the training part")

        filtered = {
            well: _filtered(injection[well], self.tau_intervals) for well in injectors
        }
        design = [
            [1.0] + [filtered[well][k] for well in injectors] for k in range(n_intervals)
        ]
        allocation, base = self._solve(
            producers, injectors, liquid, design, split
        )

        model = CrmModel(
            producers=producers,
            injectors=injectors,
            allocation=allocation,
            base_liquid=base,
            tau_intervals=self.tau_intervals,
            split=split,
            material_balance_enforced=self.enforce_material_balance,
        )
        return CrmEvaluation(
            model=model,
            holdout=self._score(model, liquid, design, split.holdout_steps),
            train=self._score(model, liquid, design, split.train_steps),
        )

    def _solve(
        self,
        producers: Sequence[str],
        injectors: Sequence[str],
        liquid: Mapping[str, Sequence[float]],
        design: Sequence[Sequence[float]],
        split: CrmSplit,
    ) -> tuple[tuple[tuple[float, ...], ...], tuple[float, ...]]:
        width = len(injectors) + 1
        normal: dict[str, tuple[list[list[float]], list[float]]] = {}
        for producer in producers:
            gram = [[0.0] * width for _ in range(width)]
            moment = [0.0] * width
            target = liquid[producer]
            for k in split.train_steps:
                row = design[k]
                observed = target[k]
                for a in range(width):
                    value = row[a]
                    if value == 0.0:
                        continue
                    moment[a] += value * observed
                    for b in range(width):
                        gram[a][b] += value * row[b]
            normal[producer] = (gram, moment)

        coefficients = {
            producer: [
                sum(liquid[producer][k] for k in split.train_steps) / split.train_intervals
            ]
            + [0.0] * len(injectors)
            for producer in producers
        }

        for _ in range(_MAX_SWEEPS):
            shift = 0.0
            for producer in producers:
                gram, moment = normal[producer]
                current = coefficients[producer]
                for a in range(width):
                    diagonal = gram[a][a] + (self.ridge if a > 0 else 0.0)
                    if diagonal <= 0.0:
                        continue
                    residual = moment[a] - sum(
                        gram[a][b] * current[b] for b in range(width) if b != a
                    )
                    value = residual / diagonal
                    if value < 0.0:
                        value = 0.0
                    shift = max(shift, abs(value - current[a]))
                    current[a] = value
            if self.enforce_material_balance:
                for column in range(1, width):
                    total = sum(coefficients[p][column] for p in producers)
                    if total > 1.0:
                        for producer in producers:
                            coefficients[producer][column] /= total
            if shift < _CONVERGENCE_TOLERANCE:
                break

        allocation = tuple(
            tuple(coefficients[producer][1:]) for producer in producers
        )
        base = tuple(coefficients[producer][0] for producer in producers)
        return allocation, base

    @staticmethod
    def _score(
        model: CrmModel,
        liquid: Mapping[str, Sequence[float]],
        design: Sequence[Sequence[float]],
        steps: range,
    ) -> CrmMetrics:
        actual: list[float] = []
        predicted: list[float] = []
        for index, producer in enumerate(model.producers):
            row = model.allocation[index]
            intercept = model.base_liquid[index]
            for k in steps:
                actual.append(liquid[producer][k])
                predicted.append(
                    intercept
                    + sum(
                        coefficient * design[k][1 + column]
                        for column, coefficient in enumerate(row)
                    )
                )
        return _metrics(actual, predicted)


__all__ = [
    "CrmBaseline",
]
