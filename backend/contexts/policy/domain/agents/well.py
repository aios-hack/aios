from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.schedule.domain.schedule import ControlEvent
from backend.contexts.policy.domain.policy import Rule

from backend.contexts.policy.domain.agents.base import Proposal
from backend.contexts.policy.domain.levels import Level, LeveledTraceEntry, execute_well
from backend.contexts.policy.domain.state import PolicyState, RuleContext

WELL_EXECUTOR = "WellExecutor"


@dataclass(frozen=True, slots=True)
class WellExecutor:
    name: str = WELL_EXECUTOR
    level: Level = Level.WELL
    responsibilities: tuple[str, ...] = (
        "quantises the setpoint by the controller step and never emits negative values",
        "holds the liquid rate ceiling of the Methodology for SET_LRAT",
        "vetoes a decision that falls inside a well downtime window",
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
                f"{self.name}: the executor does not invent decisions; it is handed "
                f"an event and the rule that produced it"
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
