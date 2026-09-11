from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from backend.contexts.schedule.domain.schedule import Role

from backend.contexts.connectivity.domain.deck_schedule import DeckSchedule


@dataclass(frozen=True, slots=True)
class SetpointChange:
    deck_date_index: int
    when: date
    well: str
    role: Role
    previous_m3_per_day: float
    current_m3_per_day: float

    @property
    def absolute_step_m3_per_day(self) -> float:
        return abs(self.current_m3_per_day - self.previous_m3_per_day)

    @property
    def relative_step(self) -> float:
        if self.previous_m3_per_day <= 0.0:
            raise ValueError(
                f"{self.well}: the relative step is undefined from a zero level"
            )
        return self.absolute_step_m3_per_day / self.previous_m3_per_day


@dataclass(frozen=True, slots=True)
class StepDistribution:
    role: Role
    records: int
    changes: tuple[SetpointChange, ...]
    levels: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.records <= 0:
            raise ValueError(f"{self.role.name}: no records in the control window")
        if not self.levels:
            raise ValueError(f"{self.role.name}: no setpoints in the control window")

    @property
    def change_share(self) -> float:
        return len(self.changes) / self.records

    @property
    def median_level_m3_per_day(self) -> float:
        return _median(self.levels)

    def absolute_steps(self) -> tuple[float, ...]:
        return tuple(sorted(c.absolute_step_m3_per_day for c in self.changes))

    def relative_steps(self) -> tuple[float, ...]:
        return tuple(
            sorted(c.relative_step for c in self.changes if c.previous_m3_per_day > 0.0)
        )

    def step_histogram(self) -> dict[float, int]:
        counted = Counter(c.absolute_step_m3_per_day for c in self.changes)
        return dict(sorted(counted.items()))

    def quantile(self, values: tuple[float, ...], share: float) -> float:
        if not values:
            raise ValueError("the quantile of an empty sample is undefined")
        if not (0.0 <= share <= 1.0):
            raise ValueError(f"share {share} outside 0…1")
        index = min(int(share * len(values)), len(values) - 1)
        return values[index]

    def dominant_step_range(self, coverage: float) -> tuple[float, float]:
        if not (0.0 < coverage <= 1.0):
            raise ValueError(f"coverage {coverage} outside 0…1")
        histogram = self.step_histogram()
        total = sum(histogram.values())
        target = coverage * total
        accumulated = 0
        low = min(histogram)
        high = low
        for step, count in histogram.items():
            accumulated += count
            high = step
            if accumulated >= target:
                break
        return low, high

    def amplitude_prior(self, coverage: float) -> tuple[float, float]:
        low, high = self.dominant_step_range(coverage)
        level = self.median_level_m3_per_day
        if level <= 0.0:
            raise ValueError(f"{self.role.name}: the median level is not positive")
        return low / level, high / level


def _median(values: tuple[float, ...]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def setpoint_changes(
    deck: DeckSchedule,
    role: Role,
    from_deck_date_index: int,
    carry_level_across_boundary: bool = True,
) -> StepDistribution:
    if role not in (Role.PROD, Role.INJ):
        raise ValueError(f"role {role.name} carries no setpoints")
    if not (0 <= from_deck_date_index < len(deck.dates)):
        raise ValueError(
            f"from_deck_date_index={from_deck_date_index} outside "
            f"0…{len(deck.dates) - 1}"
        )
    previous: dict[str, float] = {}
    changes: list[SetpointChange] = []
    levels: list[float] = []
    records = 0
    ordered = sorted(deck.records, key=lambda r: (r.deck_date_index, r.well))
    for record in ordered:
        if record.role is not role:
            continue
        in_window = record.deck_date_index >= from_deck_date_index
        if not in_window and not carry_level_across_boundary:
            continue
        if in_window:
            records += 1
            levels.append(record.setpoint_m3_per_day)
            known = previous.get(record.well)
            if known is not None and known != record.setpoint_m3_per_day:
                changes.append(
                    SetpointChange(
                        deck_date_index=record.deck_date_index,
                        when=deck.dates[record.deck_date_index],
                        well=record.well,
                        role=role,
                        previous_m3_per_day=known,
                        current_m3_per_day=record.setpoint_m3_per_day,
                    )
                )
        previous[record.well] = record.setpoint_m3_per_day
    return StepDistribution(
        role=role,
        records=records,
        changes=tuple(changes),
        levels=tuple(levels),
    )
