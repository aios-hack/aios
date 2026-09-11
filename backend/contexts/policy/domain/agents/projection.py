from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from backend.contexts.schedule.domain.schedule import ControlEvent, EventKind, MAX_LRAT_M3_PER_DAY
from backend.contexts.constraints.domain.constraints import (
    Constraints,
    DEFAULT_BHP_INJECTOR_MAX_BAR,
    DEFAULT_BHP_PRODUCER_MIN_BAR,
    bhp_limits,
)

RATE_KINDS: tuple[EventKind, ...] = (EventKind.SET_LRAT, EventKind.SET_RATE)


@dataclass(frozen=True, slots=True)
class HardConstraints:
    well_cap_m3_per_day: Mapping[str, float]
    lrat_ceiling_m3_per_day: float = MAX_LRAT_M3_PER_DAY
    bhp_producer_min_bar: float = DEFAULT_BHP_PRODUCER_MIN_BAR
    bhp_injector_max_bar: float = DEFAULT_BHP_INJECTOR_MAX_BAR

    def __post_init__(self) -> None:
        if self.lrat_ceiling_m3_per_day <= 0.0:
            raise ValueError(
                f"the liquid rate ceiling {self.lrat_ceiling_m3_per_day} "
                f"is not positive: there is nothing to clip with"
            )
        if self.bhp_producer_min_bar <= 0.0:
            raise ValueError(
                f"the lower bottomhole pressure limit of the producer "
                f"{self.bhp_producer_min_bar} bar is not positive"
            )
        if self.bhp_injector_max_bar <= self.bhp_producer_min_bar:
            raise ValueError(
                f"the bottomhole pressure corridor is empty: the upper limit "
                f"{self.bhp_injector_max_bar} bar is not above the lower "
                f"{self.bhp_producer_min_bar} bar"
            )
        for well, cap in self.well_cap_m3_per_day.items():
            if cap < 0.0:
                raise ValueError(f"{well}: negative setpoint ceiling {cap}")

    def cap_for(self, well: str, kind: EventKind) -> float:
        cap = self.well_cap_m3_per_day.get(well, float("inf"))
        if kind is EventKind.SET_LRAT:
            return min(cap, self.lrat_ceiling_m3_per_day)
        return cap


def hard_constraints_from_case(
    well_cap_m3_per_day: Mapping[str, float],
    constraints: Constraints | None = None,
    lrat_ceiling_m3_per_day: float = MAX_LRAT_M3_PER_DAY,
) -> HardConstraints:
    limits = bhp_limits(constraints if constraints is not None else Constraints())
    return HardConstraints(
        well_cap_m3_per_day=well_cap_m3_per_day,
        lrat_ceiling_m3_per_day=lrat_ceiling_m3_per_day,
        bhp_producer_min_bar=limits.producer_min_bar,
        bhp_injector_max_bar=limits.injector_max_bar,
    )


def project_to_hard_constraints(
    event: ControlEvent, constraints: HardConstraints
) -> ControlEvent:
    if event.kind not in RATE_KINDS:
        return event
    if event.value is None:
        return event
    cap = constraints.cap_for(event.well, event.kind)
    value = min(max(event.value, 0.0), cap)
    if value == event.value:
        return event
    return replace(event, value=value)
