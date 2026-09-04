"""Исполнитель скважины: квантование, потолки, вето на время простоя."""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.contracts import ControlEvent, Rule

from backend.domain.policy.agents.base import Proposal
from backend.domain.policy.levels import Level, LeveledTraceEntry, execute_well
from backend.domain.policy.state import PolicyState, RuleContext

WELL_EXECUTOR = "WellExecutor"


@dataclass(frozen=True, slots=True)
class WellExecutor:
    name: str = WELL_EXECUTOR
    level: Level = Level.WELL
    responsibilities: tuple[str, ...] = (
        "квантует уставку шагом задатчика и не выпускает отрицательных значений",
        "держит потолок дебита жидкости Методики для SET_LRAT",
        "накладывает вето на решение, попавшее внутрь простоя скважины",
    )

    def trace_agent_for(self, event: ControlEvent) -> str:
        return event.well

    def execute(
        self,
        state: PolicyState,
        context: RuleContext,
        event: ControlEvent,
        rule: Rule,
        setpoint_step_m3_per_day: float | None = None,
    ) -> tuple[ControlEvent | None, LeveledTraceEntry]:
        return execute_well(
            state,
            context,
            event,
            rule=rule,
            agent=self.trace_agent_for(event),
            setpoint_step_m3_per_day=setpoint_step_m3_per_day,
        )

    def propose(
        self,
        state: PolicyState,
        context: RuleContext,
        event: ControlEvent | None = None,
        rule: Rule | None = None,
        setpoint_step_m3_per_day: float | None = None,
    ) -> Proposal:
        if event is None or rule is None:
            raise ValueError(
                f"{self.name}: исполнитель не изобретает решений, ему подают "
                f"событие и правило, которое его породило"
            )
        applied, entry = self.execute(
            state, context, event, rule, setpoint_step_m3_per_day
        )
        decisions = () if applied is None else (applied,)
        rules = () if applied is None else (rule,)
        return Proposal(
            level=self.level,
            agent=self.trace_agent_for(event),
            decisions=decisions,
            rule_by_decision=rules,
            trace=(entry,),
        )
