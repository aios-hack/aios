from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from backend.contexts.schedule.domain.schedule import N_INTERVALS, Role
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.connectivity.domain.connectivity import Groups, Lambda
from backend.contexts.constraints.domain.config import NormativeSet

from backend.contexts.policy.domain.memory import PolicyMemory


@dataclass(frozen=True, slots=True)
class WellObservation:
    well: str
    role: Role
    is_open: bool
    liquid_rate_m3_per_day: float
    oil_rate_t_per_day: float
    injection_rate_m3_per_day: float
    setpoint_m3_per_day: float

    def __post_init__(self) -> None:
        if self.liquid_rate_m3_per_day < 0:
            raise ValueError(f"{self.well}: negative liquid rate")
        if self.oil_rate_t_per_day < 0:
            raise ValueError(f"{self.well}: negative oil rate")
        if self.injection_rate_m3_per_day < 0:
            raise ValueError(f"{self.well}: negative injectivity")

    def watercut(self, oil_density_t_per_m3: float) -> float:
        if oil_density_t_per_m3 <= 0:
            raise ValueError("oil density must be positive")
        if oil_density_t_per_m3 > 10.0:
            raise ValueError(
                f"density {oil_density_t_per_m3} was supplied not in t/m3: "
                f"kg/m3 gives a thousandfold error and a threshold at which "
                f"any well is profitable"
            )
        if self.liquid_rate_m3_per_day <= 0:
            raise ValueError(f"{self.well}: watercut is undefined at zero rate")
        oil_volume = self.oil_rate_t_per_day / oil_density_t_per_m3
        return 1.0 - oil_volume / self.liquid_rate_m3_per_day


@dataclass(frozen=True, slots=True)
class PolicyState:
    control_step: int
    wells: Mapping[str, WellObservation]

    def __post_init__(self) -> None:
        if not (0 <= self.control_step <= N_INTERVALS - 1):
            raise ValueError(
                f"control_step={self.control_step} is outside 0…{N_INTERVALS - 1}: "
                f"step {N_INTERVALS} is terminal_state and carries no decisions"
            )

    def producers(self) -> tuple[str, ...]:
        return tuple(
            sorted(w for w, obs in self.wells.items() if obs.role is Role.PROD)
        )

    def injectors(self) -> tuple[str, ...]:
        return tuple(
            sorted(w for w, obs in self.wells.items() if obs.role is Role.INJ)
        )


@dataclass(frozen=True, slots=True)
class RuleContext:
    normatives: NormativeSet
    oil_density_t_per_m3: float
    constraints: Constraints = field(default_factory=Constraints)
    influence: Lambda | None = None
    groups: Groups | None = None
    injection_budget_m3_per_day: float | None = None
    liquid_budget_m3_per_day: float | None = None
    group_liquid_budget_m3_per_day: Mapping[str, float] = field(default_factory=dict)
    memory: PolicyMemory = field(default_factory=PolicyMemory)
    group_injection_m3_per_day: Mapping[str, float] = field(default_factory=dict)
    group_offtake_m3_per_day: Mapping[str, float] = field(default_factory=dict)
    cyclic_uplift_rub_per_well: Mapping[str, float] = field(default_factory=dict)
    baseline_injection_m3_per_day: Mapping[str, float] = field(default_factory=dict)
    injection_cap_m3_per_day: Mapping[str, float] = field(default_factory=dict)
    baseline_conversion_step: Mapping[str, int] = field(default_factory=dict)
    field_pressure_bar: float | None = None
    pressure_floor_bar: float | None = None
    pressure_ceiling_bar: float | None = None

    def __post_init__(self) -> None:
        if self.oil_density_t_per_m3 <= 0:
            raise ValueError("oil density must be positive")
        if self.oil_density_t_per_m3 > 10.0:
            raise ValueError(
                f"density {self.oil_density_t_per_m3} was supplied not in t/m3 "
                f"but, judging by its magnitude, in kg/m3"
            )
        if (
            self.injection_budget_m3_per_day is not None
            and self.injection_budget_m3_per_day < 0
        ):
            raise ValueError("negative injection limit")
        if (
            self.liquid_budget_m3_per_day is not None
            and self.liquid_budget_m3_per_day < 0
        ):
            raise ValueError("negative liquid limit")
        for group_id, quota in self.group_liquid_budget_m3_per_day.items():
            if quota < 0:
                raise ValueError(
                    f"group {group_id}: negative liquid quota {quota}"
                )
        if self.field_pressure_bar is not None and self.field_pressure_bar <= 0.0:
            raise ValueError(
                f"reservoir pressure {self.field_pressure_bar} bar is not positive: "
                f"a reservoir level does not look like that"
            )
        if self.pressure_floor_bar is not None and self.pressure_floor_bar <= 0.0:
            raise ValueError(
                f"the reservoir pressure floor {self.pressure_floor_bar} bar "
                f"is not positive"
            )
        if self.pressure_ceiling_bar is not None and self.pressure_ceiling_bar <= 0.0:
            raise ValueError(
                f"the reservoir pressure ceiling {self.pressure_ceiling_bar} bar "
                f"is not positive"
            )
        if (
            self.pressure_floor_bar is not None
            and self.pressure_ceiling_bar is not None
            and self.pressure_ceiling_bar <= self.pressure_floor_bar
        ):
            raise ValueError(
                f"the reservoir pressure ceiling {self.pressure_ceiling_bar} bar "
                f"is not above the floor {self.pressure_floor_bar} bar: the corridor is empty"
            )
