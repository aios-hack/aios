from __future__ import annotations

from backend.domain.policy.agents.base import (
    Agent,
    Bound,
    BoundSense,
    Proposal,
    RankedAgent,
    Verdict,
    merge_bounds,
    merge_proposals,
)
from backend.domain.policy.agents.field import FIELD_COORDINATOR, FieldCoordinator
from backend.domain.policy.agents.group import GROUP_ALLOCATOR, GroupAllocator
from backend.domain.policy.agents.projection import (
    RATE_KINDS,
    HardConstraints,
    project_to_hard_constraints,
)
from backend.domain.policy.agents.registry import (
    DEFAULT_AGENTS,
    DEFAULT_REGISTRY,
    LEVEL_ORDER,
    WATER_AGENTS,
    WATER_REGISTRY,
    AgentRegistry,
    rank_of,
    with_agents,
)
from backend.domain.policy.agents.water import (
    WATER_AGENT,
    WATER_AGENT_RANK,
    WATER_CEILING_DECISION,
    WaterAgent,
    WaterCeiling,
    water_ceiling_for,
)
from backend.domain.policy.agents.well import WELL_EXECUTOR, WellExecutor

__all__ = [
    "Bound",
    "BoundSense",
    "RankedAgent",
    "Verdict",
    "merge_bounds",
    "merge_proposals",
    "rank_of",
    "Agent",
    "AgentRegistry",
    "DEFAULT_AGENTS",
    "DEFAULT_REGISTRY",
    "FIELD_COORDINATOR",
    "FieldCoordinator",
    "GROUP_ALLOCATOR",
    "GroupAllocator",
    "HardConstraints",
    "LEVEL_ORDER",
    "Proposal",
    "RATE_KINDS",
    "WATER_AGENT",
    "WATER_AGENTS",
    "WATER_AGENT_RANK",
    "WATER_CEILING_DECISION",
    "WATER_REGISTRY",
    "WaterAgent",
    "WaterCeiling",
    "WELL_EXECUTOR",
    "WellExecutor",
    "project_to_hard_constraints",
    "water_ceiling_for",
    "with_agents",
]
