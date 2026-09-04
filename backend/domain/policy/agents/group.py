"""Распорядитель участка: делит квоту участка между своими скважинами."""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.policy.agents.base import Proposal
from backend.domain.policy.levels import (
    GroupDecision,
    GroupLimit,
    Level,
    decide_group,
)
from backend.domain.policy.flags import RuleFlags
from backend.domain.policy.state import PolicyState, RuleContext
from backend.core.contracts import Theta

GROUP_ALLOCATOR = "GroupAllocator"


@dataclass(frozen=True, slots=True)
class GroupAllocator:
    name: str = GROUP_ALLOCATOR
    level: Level = Level.GROUP
    responsibilities: tuple[str, ...] = (
        "видит только скважины своего участка и его квоту",
        "делегирует выбор уставок правилам R0…R7, своей арифметики не имеет",
        "масштабирует запрос участка вниз, если правила запросили больше квоты",
    )

    def trace_agent_for(self, limit: GroupLimit) -> str:
        return limit.group_id

    def decide(
        self,
        state: PolicyState,
        context: RuleContext,
        theta: Theta,
        flags: RuleFlags,
        limit: GroupLimit,
    ) -> GroupDecision:
        return decide_group(state, context, theta, flags, limit)

    def propose(
        self,
        state: PolicyState,
        context: RuleContext,
        theta: Theta | None = None,
        flags: RuleFlags | None = None,
        limit: GroupLimit | None = None,
    ) -> Proposal:
        if theta is None or flags is None or limit is None:
            raise ValueError(
                f"{self.name}: без θ, флагов и квоты участка предлагать нечего"
            )
        decision = self.decide(state, context, theta, flags, limit)
        return Proposal(
            level=self.level,
            agent=self.trace_agent_for(limit),
            decisions=decision.decisions,
            rule_by_decision=decision.rule_by_decision,
            trace=decision.trace,
        )
