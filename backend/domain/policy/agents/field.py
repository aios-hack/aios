"""Координатор поля: делит лимит закачки между участками."""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.policy.agents.base import Proposal
from backend.domain.policy.levels import (
    FIELD_AGENT,
    FieldAllocation,
    Level,
    allocate_field,
)
from backend.domain.policy.flags import RuleFlags
from backend.domain.policy.state import PolicyState, RuleContext

FIELD_COORDINATOR = "FieldCoordinator"


@dataclass(frozen=True, slots=True)
class FieldCoordinator:
    name: str = FIELD_COORDINATOR
    level: Level = Level.FIELD
    responsibilities: tuple[str, ...] = (
        "читает лимит закачки поля из Constraints, а не назначает его сам",
        "считает спрос участка на воду правилом R1 по измеренной λ",
        "раздаёт квоты участкам пропорционально спросу, не превышая лимит поля",
    )
    trace_agent: str = FIELD_AGENT

    def allocate(
        self,
        state: PolicyState,
        context: RuleContext,
        flags: RuleFlags,
        field_limit_m3_per_day: float | None = None,
    ) -> FieldAllocation:
        return allocate_field(state, context, flags, field_limit_m3_per_day)

    def propose(
        self,
        state: PolicyState,
        context: RuleContext,
        flags: RuleFlags | None = None,
        field_limit_m3_per_day: float | None = None,
    ) -> Proposal:
        if flags is None:
            raise ValueError(
                f"{self.name}: без RuleFlags спрос участка считать нечем — "
                f"формула предельной ценности живёт в правиле R1"
            )
        allocation = self.allocate(state, context, flags, field_limit_m3_per_day)
        return Proposal(
            level=self.level,
            agent=self.trace_agent,
            decisions=(),
            rule_by_decision=(),
            trace=allocation.trace,
        )
