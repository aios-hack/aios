from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from contracts import N_INTERVALS, Constraints, Groups, Lambda, NormativeSet, Role

from policy.memory import PolicyMemory


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
            raise ValueError(f"{self.well}: отрицательный дебит жидкости")
        if self.oil_rate_t_per_day < 0:
            raise ValueError(f"{self.well}: отрицательный дебит нефти")
        if self.injection_rate_m3_per_day < 0:
            raise ValueError(f"{self.well}: отрицательная приёмистость")

    def watercut(self, oil_density_t_per_m3: float) -> float:
        if oil_density_t_per_m3 <= 0:
            raise ValueError("плотность нефти должна быть положительной")
        if oil_density_t_per_m3 > 10.0:
            raise ValueError(
                f"плотность {oil_density_t_per_m3} подана не в т/м³: "
                f"кг/м³ даёт ошибку в тысячу раз и порог, при котором "
                f"рентабельна любая скважина"
            )
        if self.liquid_rate_m3_per_day <= 0:
            raise ValueError(f"{self.well}: обводнённость не определена при нулевом дебите")
        oil_volume = self.oil_rate_t_per_day / oil_density_t_per_m3
        return 1.0 - oil_volume / self.liquid_rate_m3_per_day


@dataclass(frozen=True, slots=True)
class PolicyState:
    control_step: int
    wells: Mapping[str, WellObservation]

    def __post_init__(self) -> None:
        if not (0 <= self.control_step <= N_INTERVALS - 1):
            raise ValueError(
                f"control_step={self.control_step} вне 0…{N_INTERVALS - 1}: "
                f"шаг {N_INTERVALS} — terminal_state, решений не несёт"
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
    memory: PolicyMemory = field(default_factory=PolicyMemory)
    group_injection_m3_per_day: Mapping[str, float] = field(default_factory=dict)
    group_offtake_m3_per_day: Mapping[str, float] = field(default_factory=dict)
    cyclic_uplift_rub_per_well: Mapping[str, float] = field(default_factory=dict)
    #: Уставка закачки базового расписания на текущем шаге, м³/сут, по
    #: скважинам. Нужна там, где решение принимать не на чем: R1 не
    #: считает предельную ценность для нагнетательной, которой нет в λ,
    #: и без базовой уставки такая скважина молча остаётся на нуле.
    baseline_injection_m3_per_day: Mapping[str, float] = field(default_factory=dict)
    #: Физический потолок приёмистости скважины, м³/сут: её собственный
    #: исторический максимум с запасом. Правило обязано знать его до
    #: раздачи, а не узнавать постфактум срезом: вода, выданная сверх
    #: потолка, при срезе пропадает, вместо того чтобы уйти следующей
    #: по ценности скважине.
    injection_cap_m3_per_day: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.oil_density_t_per_m3 <= 0:
            raise ValueError("плотность нефти должна быть положительной")
        if self.oil_density_t_per_m3 > 10.0:
            raise ValueError(
                f"плотность {self.oil_density_t_per_m3} подана не в т/м³, "
                f"а, судя по величине, в кг/м³"
            )
        if (
            self.injection_budget_m3_per_day is not None
            and self.injection_budget_m3_per_day < 0
        ):
            raise ValueError("отрицательный лимит закачки")
