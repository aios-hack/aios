"""StateAtDate и IntervalResponse — отклик по скважинам, два типа. README.md §3."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

N_DECK_DATES = 371
N_INTERVALS = 224


class ActiveControlMode(Enum):
    """5 значений, не 2 (исправлено 14.08). README.md §3a, §4.3 базы знаний."""

    RATE_TARGET = "RATE_TARGET"
    BHP_LIMITED = "BHP_LIMITED"
    SHUT = "SHUT"
    NOT_COMMISSIONED = "NOT_COMMISSIONED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StateAtDate:
    """Мгновенные величины на дату дека. Ось — deck_date_index 0…370.

    Не диагностический тип: liquid_rate/injection_rate деньгообразующие —
    вход в определение действующего фонда и переходов состояния (§3.2
    базы знаний), а через них в содержание фонда, событийные затраты и
    EspStateMachine. Только bhp и active_control_mode — диагностика.
    """

    deck_date_index: int  # 0…370
    well: str
    liquid_rate: float  # м³/сут, фактический WLPR, не цель
    injection_rate: float  # м³/сут, фактический WWIR, не цель
    bhp: float  # бар
    active_control_mode: ActiveControlMode


@dataclass(frozen=True, slots=True)
class IntervalResponse:
    """Помесячные объёмы. Ось — control_step 0…223. Деньгообразующий тип.

    Вычисление — два шага, порядок обязателен (README.md §3b):
      1. raw_diff[i] = cumulative[i+1] − cumulative[i], i=0…369, строго
         внутри (well,) — терминальная строка i=370 в raw_diff не входит;
      2. IntervalResponse[k] = raw_diff[146 + k], k=0…223 — переиндексация.
    Сам тип не хранит deck_date_index нигде: ось дека существует только
    внутри шага 1, до проекции.
    """

    control_step: int  # 0…223
    well: str
    oil_mass_delta: float  # т
    liquid_volume_delta: float  # м³
    injection_volume_delta: float  # м³

    def __post_init__(self) -> None:
        if not (0 <= self.control_step <= N_INTERVALS - 1):
            raise ValueError(
                f"control_step={self.control_step} вне 0…{N_INTERVALS - 1}"
            )


def watercut(response: IntervalResponse, oil_density_t_per_m3: float) -> float:
    """1 − (oil_mass_delta / ρ) / liquid_volume_delta. Не канал, потребитель."""
    if response.liquid_volume_delta == 0:
        raise ValueError("liquid_volume_delta=0: обводнённость не определена")
    return 1 - (response.oil_mass_delta / oil_density_t_per_m3) / response.liquid_volume_delta


@dataclass(frozen=True, slots=True)
class StatePair:
    """Join на интервал k: response[k], current_state[k], previous_state[k].

    README.md §3c. current_state — StateAtDate[147+k] (конец интервала),
    previous_state — StateAtDate[146+k] (начало). Переход между ними —
    то, что стоит денег (§3.2 базы знаний).
    """

    control_step: int
    response: IntervalResponse
    current_state: StateAtDate
    previous_state: StateAtDate


def join_by_control_step(
    interval_responses: dict[tuple[int, str], IntervalResponse],
    states_at_date: dict[tuple[int, str], StateAtDate],
    well: str,
) -> list[StatePair]:
    """Строит тройку (response, current_state, previous_state) для всех k=0…223.

    `previous_state[0]` — StateAtDate[146], последняя историческая дата
    перед управлением. `current_state[223]` — StateAtDate[370], последняя
    дата дека. Приёмочный тест обязателен на k=0, произвольном k и k=223
    (README.md §3c) — off-by-one на границах типичный тест не ловит.
    """
    pairs = []
    for k in range(N_INTERVALS):
        pairs.append(
            StatePair(
                control_step=k,
                response=interval_responses[(k, well)],
                current_state=states_at_date[(147 + k, well)],
                previous_state=states_at_date[(146 + k, well)],
            )
        )
    return pairs
