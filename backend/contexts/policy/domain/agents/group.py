from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.policy.domain.agents.base import Proposal
from backend.contexts.policy.domain.levels import GroupDecision, GroupLimit, Level, decide_group
from backend.contexts.policy.domain.flags import RuleFlags
from backend.contexts.policy.domain.state import PolicyState, RuleContext
from backend.contexts.policy.domain.policy import Theta

GROUP_ALLOCATOR = "GroupAllocator"


@dataclass(frozen=True, slots=True)
class GroupAllocator:
    name: str = GROUP_ALLOCATOR
    level: Level = Level.GROUP
    responsibilities: tuple[str, ...] = (
        "sees only the wells of its own area and that area quota",
        "delegates the choice of setpoints to rules R0...R7 and has no arithmetic of its own",
        "scales the area request down when the rules asked for more than the quota",
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
                f"{self.name}: without theta, flags and the area quota there is nothing to propose"
            )
        decision = self.decide(state, context, theta, flags, limit)
        return Proposal(
            level=self.level,
            agent=self.trace_agent_for(limit),
            decisions=decision.decisions,
            rule_by_decision=decision.rule_by_decision,
            trace=decision.trace,
        )
