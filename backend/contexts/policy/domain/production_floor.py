from __future__ import annotations

from backend.contexts.policy.domain.hierarchy_shared import (
    PRODUCTION_FLOOR_MET,
    PRODUCTION_FLOOR_NOT_SET,
    PRODUCTION_FLOOR_UNREACHABLE,
)

from backend.contexts.policy.domain.watercut_shutins import (
    _effective_liquid,
    _shut_wells,
)

from dataclasses import (
    dataclass,
)
from typing import (
    Sequence,
)
from backend.contexts.schedule.domain.schedule import ControlEvent, Role
from backend.contexts.policy.domain.policy import Rule, TraceEntry
from backend.contexts.policy.domain.state import (
    PolicyState,
    RuleContext,
)


@dataclass(frozen=True, slots=True)
class ProductionFloorCheck:
    year: int | None
    floor_t_per_day: float | None
    predicted_t_per_day: float | None
    status: str

    @property
    def attempted(self) -> bool:
        return self.status != PRODUCTION_FLOOR_NOT_SET

    @property
    def unreachable(self) -> bool:
        return self.status == PRODUCTION_FLOOR_UNREACHABLE

    def as_entry(self, control_step: int, agent: str) -> TraceEntry:
        if self.floor_t_per_day is None or self.predicted_t_per_day is None:
            raise ValueError(
                "the production floor was not measured: there is no trace entry for it"
            )
        return TraceEntry(
            control_step=control_step,
            well=agent,
            rule=Rule.R0,
            inputs={
                "production_floor_t_per_day": self.floor_t_per_day,
                "predicted_oil_t_per_day": self.predicted_t_per_day,
                "production_floor_shortfall_t_per_day": (
                    self.floor_t_per_day - self.predicted_t_per_day
                ),
                "production_floor_year": float(self.year or 0),
            },
            decision=self.status,
        )


def predicted_oil_t_per_day(
    state: PolicyState,
    events: Sequence[ControlEvent],
    context: RuleContext,
    wells: Sequence[str],
) -> float:
    density = context.oil_density_t_per_m3
    total = 0.0
    shut = _shut_wells(events)
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None or observation.role is not Role.PROD:
            continue
        if not observation.is_open or well in shut:
            continue
        if observation.liquid_rate_m3_per_day <= 0.0:
            continue
        liquid = _effective_liquid(events, state, well)
        share = liquid / observation.liquid_rate_m3_per_day
        total += observation.oil_rate_t_per_day * share
    return total


def check_production_floor(
    state: PolicyState,
    context: RuleContext,
    events: Sequence[ControlEvent],
    wells: Sequence[str],
    year: int | None,
) -> ProductionFloorCheck:
    floors = context.constraints.production_floors
    if not floors:
        return ProductionFloorCheck(
            year=year,
            floor_t_per_day=None,
            predicted_t_per_day=None,
            status=PRODUCTION_FLOOR_NOT_SET,
        )
    if year is None:
        floor = max(float(value) for value in floors.values())
    else:
        declared = floors.get(year)
        if declared is None:
            return ProductionFloorCheck(
                year=year,
                floor_t_per_day=None,
                predicted_t_per_day=None,
                status=PRODUCTION_FLOOR_NOT_SET,
            )
        floor = float(declared)
    predicted = predicted_oil_t_per_day(state, events, context, wells)
    status = (
        PRODUCTION_FLOOR_UNREACHABLE if predicted < floor else PRODUCTION_FLOOR_MET
    )
    return ProductionFloorCheck(
        year=year,
        floor_t_per_day=floor,
        predicted_t_per_day=predicted,
        status=status,
    )


__all__ = [
    "ProductionFloorCheck",
    "check_production_floor",
    "predicted_oil_t_per_day",
]
