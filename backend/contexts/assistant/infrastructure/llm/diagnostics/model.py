from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from backend.contexts.reservoir.domain.response import IntervalResponse
from backend.contexts.schedule.domain.schedule import Role, Schedule


class TextClient(Protocol):
    def complete(self, prompt: str) -> str: ...


PATTERNS: dict[str, str] = {
    "injection_response_lag": "Отклик добычи на изменение закачки приходит с лагом",
    "wct_rise_without_oil": "Рост обводнённости без роста добычи нефти",
    "liquid_jump_flat_oil": "Резкий рост жидкости при неизменной нефти и росте воды",
    "pressure_drop_at_high_rates": "Падение забойного давления при внешне высоких дебитах",
    "injection_without_response": "Высокая закачка без полезного отклика добычи",
    "oil_rise_without_liquid": "Рост нефти без роста жидкости — признак невыработанной зоны",
}


@dataclass(frozen=True, slots=True)
class Finding:
    pattern_id: str
    name_ru: str
    well: str
    severity: str
    inputs: dict[str, float]
    control_step: int | None = None
    window: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class Thresholds:
    injection_delta_min: float
    lag_oil_delta_min: float
    max_lag_steps: int
    wct_delta_min: float
    oil_delta_max: float
    liquid_delta_min: float
    oil_delta_abs_max: float
    bhp_drop_min: float
    liquid_rate_min: float
    injection_volume_min: float
    window_steps: int
    oil_delta_min: float
    liquid_delta_max: float


def wells_with_role(schedule: Schedule, role: Role) -> tuple[str, ...]:
    return tuple(
        sorted(w for w, s in schedule.initial_state.items() if s.role is role)
    )


def steps_by_well(
    interval_response: Sequence[IntervalResponse],
) -> dict[str, dict[int, IntervalResponse]]:
    result: dict[str, dict[int, IntervalResponse]] = {}
    for row in interval_response:
        result.setdefault(row.well, {})[row.control_step] = row
    return result


def sorted_steps(rows: Mapping[int, IntervalResponse]) -> list[int]:
    return sorted(rows)
