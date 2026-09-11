from __future__ import annotations

from dataclasses import dataclass

from backend.core.contracts import EventKind, Role, Rule, TraceEntry

from backend.contexts.policy.domain.agents.base import Bound, BoundSense, Proposal
from backend.contexts.policy.domain.budget import injection_ceiling_for_well
from backend.contexts.policy.domain.levels import Level, LeveledTraceEntry
from backend.contexts.policy.domain.state import PolicyState, RuleContext

WATER_AGENT = "WaterAgent"
WATER_AGENT_RANK = 10
WATER_CEILING_DECISION = "SET_WATER_CEILING"

SOURCE_WELL_CAP = 1.0
SOURCE_FIELD_BUDGET = 2.0
NOT_DECLARED = -1.0


@dataclass(frozen=True, slots=True)
class WaterCeiling:
    well: str
    value_m3_per_day: float
    well_cap_m3_per_day: float | None
    field_budget_m3_per_day: float | None

    def __post_init__(self) -> None:
        if self.value_m3_per_day < 0.0:
            raise ValueError(
                f"{self.well}: потолок закачки по водному бюджету отрицателен "
                f"({self.value_m3_per_day} м³/сут) — ограничение не "
                f"интерпретируемо"
            )

    def binding_source(self) -> float:
        if self.field_budget_m3_per_day is None:
            return SOURCE_WELL_CAP
        if self.well_cap_m3_per_day is None:
            return SOURCE_FIELD_BUDGET
        if self.well_cap_m3_per_day <= self.field_budget_m3_per_day:
            return SOURCE_WELL_CAP
        return SOURCE_FIELD_BUDGET

    def as_bound(self) -> Bound:
        return Bound(
            well=self.well,
            kind=EventKind.SET_RATE,
            sense=BoundSense.CEILING,
            value=self.value_m3_per_day,
        )

    def as_inputs(self) -> dict[str, float]:
        return {
            "water_ceiling_m3_per_day": self.value_m3_per_day,
            "well_injection_cap_m3_per_day": (
                NOT_DECLARED
                if self.well_cap_m3_per_day is None
                else self.well_cap_m3_per_day
            ),
            "field_water_budget_m3_per_day": (
                NOT_DECLARED
                if self.field_budget_m3_per_day is None
                else self.field_budget_m3_per_day
            ),
            "binding_source": self.binding_source(),
        }


def water_ceiling_for(context: RuleContext, well: str) -> WaterCeiling | None:
    raw_cap = context.injection_cap_m3_per_day.get(well)
    if raw_cap is None:
        return None
    well_cap = float(raw_cap)
    budget = context.injection_budget_m3_per_day
    field_budget = None if budget is None else float(budget)
    value = injection_ceiling_for_well(well_cap, field_budget)
    if value is None:
        return None
    return WaterCeiling(
        well=well,
        value_m3_per_day=value,
        well_cap_m3_per_day=well_cap,
        field_budget_m3_per_day=field_budget,
    )


@dataclass(frozen=True, slots=True)
class WaterAgent:
    name: str = WATER_AGENT
    level: Level = Level.FIELD
    rank: int = WATER_AGENT_RANK
    responsibilities: tuple[str, ...] = (
        "выставляет потолок закачки на скважину из водного бюджета, "
        "объявленного в RuleContext, и не назначает бюджет сам",
        "ограничивает, а не распределяет: квоты участков остаются за "
        "FieldCoordinator, который вызывается раньше по рангу",
        "молчит, когда водных ограничений в кейсе нет, и тогда шаг совпадает "
        "с прогоном без агента бит в бит",
    )

    def ceilings(
        self, state: PolicyState, context: RuleContext
    ) -> tuple[WaterCeiling, ...]:
        found: list[WaterCeiling] = []
        for well in sorted(state.wells):
            if state.wells[well].role is not Role.INJ:
                continue
            ceiling = water_ceiling_for(context, well)
            if ceiling is None:
                continue
            found.append(ceiling)
        return tuple(found)

    def trace_for(
        self, state: PolicyState, ceilings: tuple[WaterCeiling, ...]
    ) -> tuple[LeveledTraceEntry, ...]:
        return tuple(
            LeveledTraceEntry(
                level=self.level,
                agent=self.name,
                entry=TraceEntry(
                    control_step=state.control_step,
                    well=ceiling.well,
                    rule=Rule.R1,
                    inputs=ceiling.as_inputs(),
                    decision=WATER_CEILING_DECISION,
                ),
            )
            for ceiling in ceilings
        )

    def propose(self, state: PolicyState, context: RuleContext) -> Proposal:
        ceilings = self.ceilings(state, context)
        return Proposal(
            level=self.level,
            agent=self.name,
            decisions=(),
            rule_by_decision=(),
            trace=self.trace_for(state, ceilings),
            bounds=tuple(ceiling.as_bound() for ceiling in ceilings),
        )
