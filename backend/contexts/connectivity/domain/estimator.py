from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from backend.contexts.connectivity.domain.connectivity import Lambda

from backend.contexts.connectivity.domain.doe import Orthogonality, orthogonality_of
from backend.contexts.connectivity.domain.fund import Window
from backend.contexts.connectivity.domain.sweep import WindowSteps

SINGULARITY_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class DriveMatrix:
    injectors: tuple[str, ...]
    rows: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if not self.injectors:
            raise ValueError("the drive matrix has no injectors at all")
        if not self.rows:
            raise ValueError("the drive matrix has no runs at all")
        for index, row in enumerate(self.rows):
            if len(row) != len(self.injectors):
                raise ValueError(
                    f"run {index}: {len(row)} drives for "
                    f"{len(self.injectors)} injectors"
                )

    @property
    def n_runs(self) -> int:
        return len(self.rows)

    @property
    def width(self) -> int:
        return len(self.injectors)

    def column(self, injector: str) -> tuple[float, ...]:
        index = self.injectors.index(injector)
        return tuple(row[index] for row in self.rows)

    def diagnostics(self) -> Orthogonality:
        return orthogonality_of(self.rows, SINGULARITY_TOLERANCE)


def realized_drive(
    injectors: Sequence[str],
    actual_by_run: Sequence[Mapping[str, float]],
    baseline_by_well: Mapping[str, float],
) -> DriveMatrix:
    ordered = tuple(injectors)
    missing_baseline = set(ordered) - set(baseline_by_well)
    if missing_baseline:
        raise ValueError(
            f"no baseline injectivity for {sorted(missing_baseline)}: "
            f"ΔWWIR is computed against the actual baseline run"
        )
    rows: list[tuple[float, ...]] = []
    for index, actual in enumerate(actual_by_run):
        missing = set(ordered) - set(actual)
        if missing:
            raise ValueError(
                f"run {index}: no actual injectivity for {sorted(missing)}. "
                f"The regression runs on actual ΔWWIR; substituting the planned "
                f"design levels is forbidden (section 8.2)"
            )
        rows.append(tuple(actual[well] - baseline_by_well[well] for well in ordered))
    return DriveMatrix(injectors=ordered, rows=tuple(rows))


def _transpose(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    return [list(column) for column in zip(*matrix)]


def _matmul(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]
) -> list[list[float]]:
    right_t = _transpose(right)
    return [[sum(a * b for a, b in zip(row, col)) for col in right_t] for row in left]


def _matvec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    return [sum(a * b for a, b in zip(row, vector)) for row in matrix]


def _solve_symmetric(
    matrix: Sequence[Sequence[float]], rhs: Sequence[float], ridge: float
) -> list[float]:
    size = len(matrix)
    work = [
        [matrix[i][j] + (ridge if i == j else 0.0) for j in range(size)] + [rhs[i]]
        for i in range(size)
    ]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(work[r][column]))
        if abs(work[pivot][column]) <= SINGULARITY_TOLERANCE:
            raise ValueError(
                "the normal equations are singular even with regularisation: "
                "the actual drives are linearly dependent, the lambda estimate "
                "is undefined"
            )
        work[column], work[pivot] = work[pivot], work[column]
        head = work[column]
        for row in range(size):
            if row == column:
                continue
            factor = work[row][column] / head[column]
            if factor == 0.0:
                continue
            for j in range(column, size + 1):
                work[row][j] -= factor * head[j]
    return [work[i][size] / work[i][i] for i in range(size)]


@dataclass(frozen=True, slots=True)
class Fit:
    coefficients: tuple[float, ...]
    intercept: float
    r_squared: float
    residual_sum_of_squares: float


def least_squares(
    design: Sequence[Sequence[float]],
    response: Sequence[float],
    ridge: float,
) -> Fit:
    if len(design) != len(response):
        raise ValueError(
            f"{len(design)} drive rows, {len(response)} response observations"
        )
    if not design:
        raise ValueError("a regression over an empty sample is undefined")
    if ridge < 0.0:
        raise ValueError(f"regularisation {ridge} is negative")
    augmented = [[1.0, *row] for row in design]
    transposed = _transpose(augmented)
    gram = _matmul(transposed, augmented)
    rhs = _matvec(transposed, response)
    penalty = [[0.0] * len(gram) for _ in gram]
    for index in range(1, len(gram)):
        penalty[index][index] = ridge
    regularized = [
        [gram[i][j] + penalty[i][j] for j in range(len(gram))] for i in range(len(gram))
    ]
    solution = _solve_symmetric(regularized, rhs, 0.0)
    intercept = solution[0]
    coefficients = tuple(solution[1:])
    predicted = [
        intercept + sum(c * x for c, x in zip(coefficients, row)) for row in design
    ]
    mean = sum(response) / len(response)
    total = sum((y - mean) ** 2 for y in response)
    residual = sum((y - p) ** 2 for y, p in zip(response, predicted))
    r_squared = 1.0 if total <= SINGULARITY_TOLERANCE else 1.0 - residual / total
    return Fit(
        coefficients=coefficients,
        intercept=intercept,
        r_squared=r_squared,
        residual_sum_of_squares=residual,
    )


@dataclass(frozen=True, slots=True)
class LagScan:
    lag_months: int
    r_squared: float


@dataclass(frozen=True, slots=True)
class ProducerObservation:
    producer: str
    cumulative_by_run: tuple[float, ...]
    baseline_cumulative: float

    def deltas(self) -> tuple[float, ...]:
        return tuple(value - self.baseline_cumulative for value in self.cumulative_by_run)


@dataclass(frozen=True, slots=True)
class LaggedObservations:
    lag_months: int
    producers: tuple[str, ...]
    by_producer: dict[str, ProducerObservation]

    def __post_init__(self) -> None:
        missing = set(self.producers) - set(self.by_producer)
        if missing:
            raise ValueError(f"no response observations for {sorted(missing)}")


def scan_lag(
    drive: DriveMatrix,
    observations_by_lag: Mapping[int, LaggedObservations],
    ridge: float,
) -> tuple[LagScan, ...]:
    if not observations_by_lag:
        raise ValueError("the lag grid is empty: there is nothing to search over")
    scans: list[LagScan] = []
    for lag in sorted(observations_by_lag):
        observations = observations_by_lag[lag]
        pooled = 0.0
        counted = 0
        for producer in observations.producers:
            response = observations.by_producer[producer].deltas()
            if len(response) != drive.n_runs:
                raise ValueError(
                    f"lag {lag}, {producer}: {len(response)} observations for "
                    f"{drive.n_runs} runs"
                )
            pooled += least_squares(drive.rows, response, ridge).r_squared
            counted += 1
        if counted == 0:
            raise ValueError(f"lag {lag}: no producers in the response")
        scans.append(LagScan(lag_months=lag, r_squared=pooled / counted))
    return tuple(scans)


def best_lag(scans: Sequence[LagScan]) -> LagScan:
    if not scans:
        raise ValueError("lag selection over an empty scan is undefined")
    return max(scans, key=lambda scan: (scan.r_squared, -scan.lag_months))


@dataclass(frozen=True, slots=True)
class Batch:
    drive: DriveMatrix
    observations: LaggedObservations


def _estimate_matrix(
    drive: DriveMatrix,
    observations: LaggedObservations,
    producers: Sequence[str],
    ridge: float,
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        least_squares(
            drive.rows, observations.by_producer[producer].deltas(), ridge
        ).coefficients
        for producer in producers
    )


def stability_between(
    first: Sequence[Sequence[float]], second: Sequence[Sequence[float]]
) -> float:
    if len(first) != len(second):
        raise ValueError("the batches produced different numbers of matrix rows")
    flat_first = [value for row in first for value in row]
    flat_second = [value for row in second for value in row]
    if len(flat_first) != len(flat_second):
        raise ValueError("the batches produced matrices of different shape")
    if not flat_first:
        raise ValueError("stability of an empty matrix is undefined")
    mean_first = sum(flat_first) / len(flat_first)
    mean_second = sum(flat_second) / len(flat_second)
    covariance = sum(
        (a - mean_first) * (b - mean_second) for a, b in zip(flat_first, flat_second)
    )
    variance_first = sum((a - mean_first) ** 2 for a in flat_first)
    variance_second = sum((b - mean_second) ** 2 for b in flat_second)
    denominator = (variance_first * variance_second) ** 0.5
    if denominator <= SINGULARITY_TOLERANCE:
        raise ValueError(
            "one of the batches yields a degenerate matrix with no spread: "
            "stability is undefined"
        )
    return covariance / denominator


def estimate_lambda(
    window: Window,
    producers: Sequence[str],
    batches: Sequence[Batch],
    lag_months: int,
    amplitude: float,
    achievability_ok: Mapping[str, bool],
    ridge: float,
) -> Lambda:
    if len(batches) < 2:
        raise ValueError(
            f"{len(batches)} batches: stability is measured by TWO independent "
            f"plan batches (section 8.2), it cannot be checked after the fact"
        )
    if not producers:
        raise ValueError("the influence matrix has no producers at all")
    injectors = batches[0].drive.injectors
    for index, batch in enumerate(batches):
        if batch.drive.injectors != injectors:
            raise ValueError(
                f"batch {index} was built on a different set of injectors"
            )
        if batch.observations.lag_months != lag_months:
            raise ValueError(
                f"batch {index} was observed at lag "
                f"{batch.observations.lag_months}, while the matrix is built at {lag_months}"
            )
    missing = set(injectors) - set(achievability_ok)
    if missing:
        raise ValueError(f"no achievability diagnostics for {sorted(missing)}")

    per_batch = [
        _estimate_matrix(batch.drive, batch.observations, producers, ridge)
        for batch in batches
    ]
    pooled_rows = tuple(
        tuple(
            sum(batch_matrix[row][col] for batch_matrix in per_batch) / len(per_batch)
            for col in range(len(injectors))
        )
        for row in range(len(producers))
    )
    stability = stability_between(per_batch[0], per_batch[1])

    combined_rows = tuple(row for batch in batches for row in batch.drive.rows)
    diagnostics = orthogonality_of(combined_rows, SINGULARITY_TOLERANCE)

    return Lambda(
        window_start=window.start,
        window_end=window.end,
        producers=tuple(producers),
        injectors=injectors,
        matrix=pooled_rows,
        lag_months=lag_months,
        amplitude=amplitude,
        stability=stability,
        rank=diagnostics.rank,
        condition_number=diagnostics.condition_number,
        achievability_ok=dict(achievability_ok),
    )
