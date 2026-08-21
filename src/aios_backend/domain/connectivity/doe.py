from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from aios_backend.domain.connectivity.fund import ActiveFund, Window
from aios_backend.domain.connectivity.hadamard import hadamard, is_hadamard, normalized
from aios_backend.domain.connectivity.setpoints import StepDistribution

RUN_BLOCK = 4
LEVEL_HIGH = 1
LEVEL_LOW = -1


class Level(Enum):
    HIGH = "HIGH"
    LOW = "LOW"


def plan_runs(plan_width: int) -> int:
    if plan_width < 1:
        raise ValueError("план на пустой фонд не строится")
    runs = RUN_BLOCK
    while runs < plan_width + 1:
        runs += RUN_BLOCK
    return runs


@dataclass(frozen=True, slots=True)
class Amplitude:
    base_level_m3_per_day: float
    step_low_m3_per_day: float
    step_high_m3_per_day: float

    def __post_init__(self) -> None:
        if self.base_level_m3_per_day <= 0.0:
            raise ValueError("медианный уровень закачки не положителен")
        if self.step_low_m3_per_day <= 0.0:
            raise ValueError("нижний шаг амплитуды не положителен")
        if self.step_high_m3_per_day < self.step_low_m3_per_day:
            raise ValueError(
                f"верхний шаг {self.step_high_m3_per_day} меньше нижнего "
                f"{self.step_low_m3_per_day}"
            )

    @property
    def step_m3_per_day(self) -> float:
        return (self.step_low_m3_per_day + self.step_high_m3_per_day) / 2.0

    @property
    def relative_low(self) -> float:
        return self.step_low_m3_per_day / self.base_level_m3_per_day

    @property
    def relative_high(self) -> float:
        return self.step_high_m3_per_day / self.base_level_m3_per_day

    def target(self, level: Level, current_m3_per_day: float) -> float:
        step = self.step_m3_per_day
        if level is Level.HIGH:
            return current_m3_per_day + step
        return max(current_m3_per_day - step, 0.0)


def amplitude_from_prior(
    distribution: StepDistribution, coverage: float
) -> Amplitude:
    low, high = distribution.dominant_step_range(coverage)
    return Amplitude(
        base_level_m3_per_day=distribution.median_level_m3_per_day,
        step_low_m3_per_day=low,
        step_high_m3_per_day=high,
    )


@dataclass(frozen=True, slots=True)
class PlanRow:
    run_index: int
    levels: dict[str, Level]

    def __post_init__(self) -> None:
        if not self.levels:
            raise ValueError(f"прогон {self.run_index} без единой скважины")

    def high(self) -> tuple[str, ...]:
        return tuple(
            sorted(w for w, level in self.levels.items() if level is Level.HIGH)
        )

    def low(self) -> tuple[str, ...]:
        return tuple(
            sorted(w for w, level in self.levels.items() if level is Level.LOW)
        )

    def balance(self) -> tuple[int, int]:
        return len(self.high()), len(self.low())


@dataclass(frozen=True, slots=True)
class DoEPlan:
    window: Window
    injectors: tuple[str, ...]
    rows: tuple[PlanRow, ...]
    amplitude: Amplitude
    seed: int

    def __post_init__(self) -> None:
        if not self.injectors:
            raise ValueError(
                "план на окно без активных нагнетательных не строится: "
                "измерять было бы нечего"
            )
        if len(set(self.injectors)) != len(self.injectors):
            raise ValueError("скважина названа в плане дважды")
        for row in self.rows:
            if set(row.levels) != set(self.injectors):
                raise ValueError(
                    f"прогон {row.run_index}: уровни заданы не для всех "
                    f"нагнетательных окна"
                )

    @property
    def plan_width(self) -> int:
        return len(self.injectors)

    @property
    def n_runs(self) -> int:
        return len(self.rows)

    def design_matrix(self) -> tuple[tuple[int, ...], ...]:
        return tuple(
            tuple(
                LEVEL_HIGH if row.levels[well] is Level.HIGH else LEVEL_LOW
                for well in self.injectors
            )
            for row in self.rows
        )

    @property
    def padding_columns(self) -> int:
        return self.n_runs - self.plan_width

    def column_balance(self) -> dict[str, tuple[int, int]]:
        matrix = self.design_matrix()
        balance: dict[str, tuple[int, int]] = {}
        for index, well in enumerate(self.injectors):
            column = [row[index] for row in matrix]
            balance[well] = (
                column.count(LEVEL_HIGH),
                column.count(LEVEL_LOW),
            )
        return balance

    def column_balanced(self) -> bool:
        return all(abs(high - low) <= 1 for high, low in self.column_balance().values())

    def row_balanced(self) -> bool:
        return self.padding_columns == 0 and all(
            abs(high - low) <= 1 for high, low in (row.balance() for row in self.rows)
        )

    def column_of(self, injector: str) -> tuple[int, ...]:
        if injector not in self.injectors:
            raise ValueError(f"{injector} не входит в план окна")
        index = self.injectors.index(injector)
        return tuple(row[index] for row in self.design_matrix())

    def targets(
        self, run_index: int, current_by_well: Mapping[str, float]
    ) -> dict[str, float]:
        row = self.rows[run_index]
        missing = set(self.injectors) - set(current_by_well)
        if missing:
            raise ValueError(
                f"нет текущего уровня закачки для {sorted(missing)}: "
                f"целевой уровень плана назначается от факта"
            )
        return {
            well: self.amplitude.target(row.levels[well], current_by_well[well])
            for well in self.injectors
        }


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
            raise ValueError(f"допуск недобора {self.tolerance} вне [0, 1)")

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
        raise ValueError("пустая матрица плана не диагностируется")
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
            f"фактических прогонов {len(actual_by_run)}, а план требует "
            f"{plan.n_runs}"
        )
    rows: list[tuple[float, ...]] = []
    for actual in actual_by_run:
        missing = set(plan.injectors) - set(actual)
        if missing:
            raise ValueError(f"нет фактической приёмистости для {sorted(missing)}")
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
        raise ValueError("число целевых и фактических прогонов разошлось")
    if len(targets_by_run) != plan.n_runs:
        raise ValueError(
            f"сверка на {len(targets_by_run)} прогонов при плане в {plan.n_runs}"
        )
    checks: list[AchievabilityCheck] = []
    for run_index, (target, actual) in enumerate(zip(targets_by_run, actual_by_run)):
        for well in plan.injectors:
            if well not in target or well not in actual:
                raise ValueError(
                    f"прогон {run_index}: нет сверки по скважине {well}"
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


def _rotated(order: Sequence[str], seed: int) -> tuple[str, ...]:
    if not order:
        return ()
    offset = seed % len(order)
    return tuple(order[offset:]) + tuple(order[:offset])


def plackett_burman(
    window: Window,
    fund: ActiveFund,
    amplitude: Amplitude,
    seed: int,
) -> DoEPlan:
    injectors = tuple(sorted(fund.injectors))
    if not injectors:
        raise ValueError(
            f"на окно {window.start}…{window.end} активных нагнетательных нет: "
            f"ширина плана — свойство окна, а не константа"
        )
    runs = plan_runs(len(injectors))
    matrix = normalized(hadamard(runs))
    if not is_hadamard(matrix):
        raise ValueError(f"построенная матрица порядка {runs} не ортогональна")
    assignment = _rotated(injectors, seed)
    rows: list[PlanRow] = []
    for run_index in range(1, runs):
        levels = {
            assignment[column - 1]: (
                Level.HIGH if matrix[run_index][column] == LEVEL_HIGH else Level.LOW
            )
            for column in range(1, len(assignment) + 1)
        }
        rows.append(PlanRow(run_index=run_index - 1, levels=levels))
    return DoEPlan(
        window=window,
        injectors=injectors,
        rows=tuple(rows),
        amplitude=amplitude,
        seed=seed,
    )


def plans_for_windows(
    sliced: Sequence[tuple[Window, ActiveFund]],
    amplitude: Amplitude,
    seed: int,
) -> tuple[DoEPlan, ...]:
    return tuple(
        plackett_burman(window, fund, amplitude, seed) for window, fund in sliced
    )
