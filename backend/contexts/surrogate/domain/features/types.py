from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Mapping

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.surrogate.domain.errors import FeatureError
from backend.contexts.schedule.domain.schedule import (
    Availability,
    EventKind,
    OperatingStatus,
    Role,
    WellState,
)


_EVENT_ORDER = {
    EventKind.SET_LRAT: 0,
    EventKind.CONVERT_INJ: 1,
    EventKind.SET_RATE: 2,
    EventKind.OPEN: 3,
    EventKind.SHUT: 3,
}


@dataclass(frozen=True, slots=True)
class HistoryTargets:
    target_liquid_m3: float
    target_injection_m3: float
    event_count: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.target_liquid_m3) or not math.isfinite(
            self.target_injection_m3
        ):
            raise FeatureError("historical cumulative targets must be finite")
        if self.target_liquid_m3 < 0 or self.target_injection_m3 < 0:
            raise FeatureError("historical cumulative targets cannot be negative")
        if self.event_count < 0:
            raise FeatureError("the historical event count cannot be negative")


@dataclass(frozen=True, slots=True)
class FeatureContext:
    control_dates: tuple[date, ...]
    history_start: date
    history_prefix_hash: str
    history_targets: Mapping[str, HistoryTargets]
    static_features: Mapping[str, Mapping[str, float]]
    lambda_windows: tuple[Lambda, ...]


@dataclass(frozen=True, slots=True)
class WellStepFeatures:
    control_step: int
    interval_start: date
    interval_end: date
    well: str
    availability: Availability
    role: Role
    operating_status: OperatingStatus
    setpoint_m3_per_day: float
    effective_target_rate_m3_per_day: float
    cumulative_target_liquid_m3: float
    cumulative_target_injection_m3: float
    cumulative_neighbor_injection_m3: float
    current_neighbor_injection_m3_per_day: float
    event_count: int
    fixed_event_count: int
    static_values: tuple[float, ...]
    lambda_window_start: date
    lambda_window_end: date


@dataclass(frozen=True, slots=True)
class LambdaEdgeFeature:
    control_step: int
    producer: str
    injector: str
    coefficient: float
    injector_target_rate_m3_per_day: float
    injector_cumulative_target_injection_m3: float
    weighted_target_rate_m3_per_day: float
    weighted_cumulative_target_injection_m3: float


@dataclass(frozen=True, slots=True)
class SurrogateInput:
    canonical_schedule_hash: str
    wells: tuple[str, ...]
    static_feature_names: tuple[str, ...]
    nodes: tuple[WellStepFeatures, ...]
    lambda_edges: tuple[LambdaEdgeFeature, ...]


@dataclass(slots=True)
class _MutableState:
    availability: Availability
    role: Role
    operating_status: OperatingStatus
    setpoint: float

    @classmethod
    def from_contract(cls, state: WellState) -> _MutableState:
        return cls(
            availability=state.availability,
            role=state.role,
            operating_status=state.operating_status,
            setpoint=state.setpoint,
        )

    @property
    def effective_target(self) -> float:
        if (
            self.availability is Availability.AVAILABLE
            and self.operating_status is OperatingStatus.OPEN
        ):
            return self.setpoint
        return 0.0


__all__ = [
    "FeatureContext",
    "HistoryTargets",
    "LambdaEdgeFeature",
    "SurrogateInput",
    "WellStepFeatures",
]
