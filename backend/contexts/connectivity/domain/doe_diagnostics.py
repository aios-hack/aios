from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from backend.contexts.connectivity.domain.doe_plan import Amplitude, DoEPlan

@dataclass(frozen=True, slots=True)
class Orthogonality:
    rank: int
    condition_number: float
    max_abs_correlation: float
    balanced: bool

    @property
    def full_rank(self) -> bool:
        return self.rank > 0


@dataclass(frozen=True, slots=True)
class AchievabilityCheck:
    run_index: int
    well: str
    target_m3_per_day: float
    actual_m3_per_day: float

    @property
    def shortfall_m3_per_day(self) -> float:
        return max(self.target_m3_per_day - self.actual_m3_per_day, 0.0)

    @property
    def achieved(self) -> bool:
        return self.shortfall_m3_per_day <= 0.0

    @property
    def relative_shortfall(self) -> float:
        if self.target_m3_per_day <= 0.0:
            return 0.0
        return self.shortfall_m3_per_day / self.target_m3_per_day


@dataclass(frozen=True, slots=True)
class AchievabilityReport:
    checks: tuple[AchievabilityCheck, ...]
    tolerance: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.tolerance < 1.0):
            raise ValueError(f"shortfall tolerance {self.tolerance} outside [0, 1)")

    def shortfalls(self) -> tuple[AchievabilityCheck, ...]:
        return tuple(
            c for c in self.checks if c.relative_shortfall > self.tolerance
        )

    def achievability_ok(self) -> dict[str, bool]:
        failing = {c.well for c in self.shortfalls()}
        return {c.well: c.well not in failing for c in self.checks}

    def systematic_shortfall(self) -> bool:
        wells = {c.well for c in self.checks}
        if not wells:
            return False
        failing = {c.well for c in self.shortfalls()}
        return len(failing) * 2 > len(wells)

    def suggested_amplitude(self, amplitude: Amplitude) -> Amplitude:
        if not self.systematic_shortfall():
            return amplitude
        return Amplitude(
            base_level_m3_per_day=amplitude.base_level_m3_per_day,
            step_low_m3_per_day=amplitude.step_low_m3_per_day / 2.0,
            step_high_m3_per_day=amplitude.step_high_m3_per_day / 2.0,
        )


def _dot(first: Sequence[float], second: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(first, second))


def _gram(columns: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[_dot(a, b) for b in columns] for a in columns]


def _start_vectors(size: int) -> tuple[list[float], ...]:
    starts = [[1.0] * size]
    for index in range(size):
        vector = [1.0] * size
        vector[index] = -1.0
        starts.append(vector)
    for index in range(size):
        vector = [0.0] * size
        vector[index] = 1.0
        starts.append(vector)
    return tuple(starts)


def _eigen_bounds(gram: list[list[float]]) -> tuple[float, float]:
    size = len(gram)
    starts = _start_vectors(size)
    largest = max(_power_iterate(gram, start) for start in starts)
    if largest == 0.0:
        return 0.0, 0.0
    shifted = [
        [(largest if i == j else 0.0) - gram[i][j] for j in range(size)]
        for i in range(size)
    ]
    shifted_top = max(_power_iterate(shifted, start) for start in starts)
    smallest = largest - shifted_top
    return largest, max(smallest, 0.0)


def _power_iterate(
    matrix: list[list[float]], vector: list[float], iterations: int = 200
) -> float:
    current = list(vector)
    value = 0.0
    for _ in range(iterations):
        product = [
            sum(matrix[i][j] * current[j] for j in range(len(current)))
            for i in range(len(current))
        ]
        norm = max(abs(x) for x in product)
        if norm == 0.0:
            return 0.0
        current = [x / norm for x in product]
        value = norm
    return value


def _column_rank(columns: Sequence[Sequence[float]], tolerance: float) -> int:
    rows = list(zip(*columns)) if columns else []
    work = [list(map(float, row)) for row in rows]
    rank = 0
    column_count = len(columns)
    row_index = 0
    for column in range(column_count):
        pivot = None
        for candidate in range(row_index, len(work)):
            if abs(work[candidate][column]) > tolerance:
                pivot = candidate
                break
        if pivot is None:
            continue
        work[row_index], work[pivot] = work[pivot], work[row_index]
        head = work[row_index]
        for candidate in range(len(work)):
            if candidate == row_index:
                continue
            factor = work[candidate][column] / head[column]
            if factor == 0.0:
                continue
            for j in range(column_count):
                work[candidate][j] -= factor * head[j]
        rank += 1
        row_index += 1
        if row_index == len(work):
            break
    return rank


def orthogonality_of(
    matrix: Sequence[Sequence[float]], tolerance: float = 1e-9
) -> Orthogonality:
    if not matrix:
        raise ValueError("an empty plan matrix cannot be diagnosed")
    columns = list(zip(*matrix))
    rank = _column_rank(columns, tolerance)
    gram = _gram(columns)
    largest, smallest = _eigen_bounds(gram)
    if rank < len(columns) or smallest <= tolerance:
        condition_number = float("inf")
    else:
        condition_number = largest / smallest
    worst = 0.0
    for first in range(len(columns)):
        for second in range(first + 1, len(columns)):
            norm_first = _dot(columns[first], columns[first]) ** 0.5
            norm_second = _dot(columns[second], columns[second]) ** 0.5
            if norm_first == 0.0 or norm_second == 0.0:
                worst = 1.0
                continue
            correlation = abs(
                _dot(columns[first], columns[second]) / (norm_first * norm_second)
            )
            worst = max(worst, correlation)
    balanced = all(
        abs(sum(1 for value in row if value > 0) - sum(1 for value in row if value < 0))
        <= 1
        for row in matrix
    )
    return Orthogonality(
        rank=rank,
        condition_number=condition_number,
        max_abs_correlation=worst,
        balanced=balanced,
    )


def realized_matrix(
    plan: DoEPlan,
    actual_by_run: Sequence[Mapping[str, float]],
    baseline_by_well: Mapping[str, float],
) -> tuple[tuple[float, ...], ...]:
    if len(actual_by_run) != plan.n_runs:
        raise ValueError(
            f"{len(actual_by_run)} actual runs, while the plan requires "
            f"{plan.n_runs}"
        )
    rows: list[tuple[float, ...]] = []
    for actual in actual_by_run:
        missing = set(plan.injectors) - set(actual)
        if missing:
            raise ValueError(f"no actual injectivity for {sorted(missing)}")
        rows.append(
            tuple(
                actual[well] - baseline_by_well[well] for well in plan.injectors
            )
        )
    return tuple(rows)


def achievability(
    plan: DoEPlan,
    targets_by_run: Sequence[Mapping[str, float]],
    actual_by_run: Sequence[Mapping[str, float]],
    tolerance: float,
) -> AchievabilityReport:
    if len(targets_by_run) != len(actual_by_run):
        raise ValueError("the number of target and actual runs disagrees")
    if len(targets_by_run) != plan.n_runs:
        raise ValueError(
            f"reconciliation over {len(targets_by_run)} runs while the plan has {plan.n_runs}"
        )
    checks: list[AchievabilityCheck] = []
    for run_index, (target, actual) in enumerate(zip(targets_by_run, actual_by_run)):
        for well in plan.injectors:
            if well not in target or well not in actual:
                raise ValueError(
                    f"run {run_index}: no reconciliation for well {well}"
                )
            checks.append(
                AchievabilityCheck(
                    run_index=run_index,
                    well=well,
                    target_m3_per_day=target[well],
                    actual_m3_per_day=actual[well],
                )
            )
    return AchievabilityReport(checks=tuple(checks), tolerance=tolerance)
