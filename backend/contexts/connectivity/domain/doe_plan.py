from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from backend.contexts.connectivity.domain.fund import Window
from backend.contexts.connectivity.domain.setpoints import StepDistribution

RUN_BLOCK = 4
LEVEL_HIGH = 1
LEVEL_LOW = -1


class Level(Enum):
    HIGH = "HIGH"
    LOW = "LOW"


def plan_runs(plan_width: int) -> int:
    if plan_width < 1:
        raise ValueError("a plan cannot be built for an empty well stock")
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
            raise ValueError("the median injection level is not positive")
        if self.step_low_m3_per_day <= 0.0:
            raise ValueError("the lower amplitude step is not positive")
        if self.step_high_m3_per_day < self.step_low_m3_per_day:
            raise ValueError(
                f"the upper step {self.step_high_m3_per_day} is below the lower "
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
            raise ValueError(f"run {self.run_index} has no wells at all")

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
                "a plan cannot be built for a window without active injectors: "
                "there would be nothing to measure"
            )
        if len(set(self.injectors)) != len(self.injectors):
            raise ValueError("a well is named twice in the plan")
        for row in self.rows:
            if set(row.levels) != set(self.injectors):
                raise ValueError(
                    f"run {row.run_index}: levels are not given for every "
                    f"injector of the window"
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
            raise ValueError(f"{injector} is not part of the window plan")
        index = self.injectors.index(injector)
        return tuple(row[index] for row in self.design_matrix())

    def targets(
        self, run_index: int, current_by_well: Mapping[str, float]
    ) -> dict[str, float]:
        row = self.rows[run_index]
        missing = set(self.injectors) - set(current_by_well)
        if missing:
            raise ValueError(
                f"no current injection level for {sorted(missing)}: "
                f"the plan target level is set relative to the actual one"
            )
        return {
            well: self.amplitude.target(row.levels[well], current_by_well[well])
            for well in self.injectors
        }

