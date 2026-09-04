"""Единственный шлюз между предложением агента и расписанием.

Протокол: агенты предлагают, проекция отсекает, OPM решает. Уставка, не
прошедшая `project_to_hard_constraints`, в расписание попадать не должна —
это проверяет тест шлюза.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from backend.core.contracts import MAX_LRAT_M3_PER_DAY, ControlEvent, EventKind

RATE_KINDS: tuple[EventKind, ...] = (EventKind.SET_LRAT, EventKind.SET_RATE)


@dataclass(frozen=True, slots=True)
class HardConstraints:
    """Жёсткие пределы уставки: то, что нельзя обойти ни одному агенту."""

    well_cap_m3_per_day: Mapping[str, float]
    lrat_ceiling_m3_per_day: float = MAX_LRAT_M3_PER_DAY

    def __post_init__(self) -> None:
        if self.lrat_ceiling_m3_per_day <= 0.0:
            raise ValueError(
                f"потолок дебита жидкости {self.lrat_ceiling_m3_per_day} "
                f"не положителен: отсекать нечем"
            )
        for well, cap in self.well_cap_m3_per_day.items():
            if cap < 0.0:
                raise ValueError(f"{well}: отрицательный потолок уставки {cap}")

    def cap_for(self, well: str, kind: EventKind) -> float:
        cap = self.well_cap_m3_per_day.get(well, float("inf"))
        if kind is EventKind.SET_LRAT:
            return min(cap, self.lrat_ceiling_m3_per_day)
        return cap


def project_to_hard_constraints(
    event: ControlEvent, constraints: HardConstraints
) -> ControlEvent:
    """Спроецировать одно предложение на жёсткие ограничения скважины."""

    if event.kind not in RATE_KINDS:
        return event
    if event.value is None:
        return event
    cap = constraints.cap_for(event.well, event.kind)
    value = min(max(event.value, 0.0), cap)
    if value == event.value:
        return event
    return replace(event, value=value)
