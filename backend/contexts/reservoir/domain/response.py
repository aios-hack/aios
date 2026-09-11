from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.contexts.reservoir.domain.horizon import HORIZON

N_DECK_DATES = HORIZON.n_deck_dates
N_INTERVALS = HORIZON.n_intervals


class ActiveControlMode(Enum):

    RATE_TARGET = "RATE_TARGET"
    BHP_LIMITED = "BHP_LIMITED"
    SHUT = "SHUT"
    NOT_COMMISSIONED = "NOT_COMMISSIONED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StateAtDate:

    deck_date_index: int
    well: str
    liquid_rate: float
    oil_rate: float
    injection_rate: float
    thp: float
    bhp: float
    well_efficiency: float
    active_control_mode: ActiveControlMode


@dataclass(frozen=True, slots=True)
class IntervalResponse:

    control_step: int
    well: str
    oil_mass_delta: float
    liquid_volume_delta: float
    injection_volume_delta: float

    def __post_init__(self) -> None:
        if not (0 <= self.control_step <= N_INTERVALS - 1):
            raise ValueError(
                f"control_step={self.control_step} outside 0…{N_INTERVALS - 1}"
            )


def is_excluded_by_negative_rule(response: IntervalResponse) -> bool:
    return (
        response.liquid_volume_delta < 0
        or response.oil_mass_delta < 0
        or response.injection_volume_delta < 0
    )


def watercut(response: IntervalResponse, oil_density_t_per_m3: float) -> float:
    if response.liquid_volume_delta == 0:
        raise ValueError("liquid_volume_delta=0: watercut is undefined")
    return 1 - (response.oil_mass_delta / oil_density_t_per_m3) / response.liquid_volume_delta


@dataclass(frozen=True, slots=True)
class StatePair:

    control_step: int
    response: IntervalResponse
    current_state: StateAtDate
    previous_state: StateAtDate


def join_by_control_step(
    interval_responses: dict[tuple[int, str], IntervalResponse],
    states_at_date: dict[tuple[int, str], StateAtDate],
    well: str,
) -> list[StatePair]:
    pairs = []
    for k in range(N_INTERVALS):
        pairs.append(
            StatePair(
                control_step=k,
                response=interval_responses[(k, well)],
                current_state=states_at_date[(HORIZON.history_offset + 1 + k, well)],
                previous_state=states_at_date[(HORIZON.history_offset + k, well)],
            )
        )
    return pairs
