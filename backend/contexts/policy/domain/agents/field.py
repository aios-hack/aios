from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.policy.domain.agents.base import Proposal
from backend.contexts.policy.domain.levels import (
    FIELD_AGENT,
    FieldAllocation,
    Level,
    allocate_field,
)
from backend.contexts.policy.domain.flags import RuleFlags
from backend.contexts.policy.domain.state import PolicyState, RuleContext

FIELD_COORDINATOR = "FieldCoordinator"


@dataclass(frozen=True, slots=True)
class FieldCoordinator:
    name: str = FIELD_COORDINATOR
    level: Level = Level.FIELD
    responsibilities: tuple[str, ...] = (
        "reads the field injection limit from Constraints instead of setting it itself",
        "computes the area demand for water with rule R1 from the measured lambda",
        "hands quotas to areas in proportion to demand without exceeding the field limit",
        "reads the field liquid limit and splits it by the marginal value of offtake",
    )
    trace_agent: str = FIELD_AGENT

    def allocate(
        self,
        state: PolicyState,
        context: RuleContext,
        flags: RuleFlags,
        field_limit_m3_per_day: float | None = None,
        field_liquid_limit_m3_per_day: float | None = None,
    ) -> FieldAllocation:
        return allocate_field(
            state,
            context,
            flags,
            field_limit_m3_per_day,
            field_liquid_limit_m3_per_day,
        )

    def propose(
        self,
        state: PolicyState,
        context: RuleContext,
        flags: RuleFlags | None = None,
        field_limit_m3_per_day: float | None = None,
        field_liquid_limit_m3_per_day: float | None = None,
    ) -> Proposal:
        if flags is None:
            raise ValueError(
                f"{self.name}: without RuleFlags there is nothing to compute the area demand with - "
                f"the marginal value formula lives in rule R1"
            )
        allocation = self.allocate(
            state,
            context,
            flags,
            field_limit_m3_per_day,
            field_liquid_limit_m3_per_day,
        )
        return Proposal(
            level=self.level,
            agent=self.trace_agent,
            decisions=(),
            rule_by_decision=(),
            trace=allocation.trace,
        )
