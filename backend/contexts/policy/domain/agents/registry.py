from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.policy.domain.agents.base import DEFAULT_RANK, Agent
from backend.contexts.policy.domain.agents.field import FieldCoordinator
from backend.contexts.policy.domain.agents.group import GroupAllocator
from backend.contexts.policy.domain.agents.pressure import PressureAgent
from backend.contexts.policy.domain.agents.water import WaterAgent
from backend.contexts.policy.domain.agents.well import WellExecutor
from backend.contexts.policy.domain.levels import Level

LEVEL_ORDER: tuple[Level, ...] = (Level.FIELD, Level.GROUP, Level.WELL)


def rank_of(agent: Agent) -> int:
    rank = getattr(agent, "rank", DEFAULT_RANK)
    if not isinstance(rank, int) or isinstance(rank, bool):
        raise ValueError(
            f"{getattr(agent, 'name', '<unnamed>')}: rank={rank!r} is not an integer "
            f"number: the invocation order is not comparable"
        )
    return rank


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    agents: tuple[Agent, ...]

    def __post_init__(self) -> None:
        if not self.agents:
            raise ValueError("the agent registry is empty: there is nobody to execute the hierarchy step")
        seen: set[str] = set()
        ranks: dict[tuple[Level, int], str] = {}
        for agent in self.agents:
            if not agent.name:
                raise ValueError("an agent without a name: the registry is not addressable")
            if agent.name in seen:
                raise ValueError(f"the agent name {agent.name} occurs twice")
            seen.add(agent.name)
            if not agent.responsibilities:
                raise ValueError(
                    f"{agent.name}: an agent without a described responsibility: "
                    f"there will be nothing to name its role with when it is defended"
                )
            if agent.level not in LEVEL_ORDER:
                raise ValueError(f"{agent.name}: unknown level {agent.level}")
            slot = (agent.level, rank_of(agent))
            taken = ranks.get(slot)
            if taken is not None:
                raise ValueError(
                    f"{agent.name} and {taken} declared rank {slot[1]} at level "
                    f"{agent.level.value}: which of them constrains the other is undefined"
                )
            ranks[slot] = agent.name

    def names(self) -> tuple[str, ...]:
        return tuple(agent.name for agent in self.agents)

    def of(self, name: str) -> Agent:
        for agent in self.agents:
            if agent.name == name:
                return agent
        raise ValueError(f"agent {name} is not in the registry")

    def by_level(self, level: Level) -> tuple[Agent, ...]:
        found = [agent for agent in self.agents if agent.level is level]
        return tuple(sorted(found, key=lambda agent: (rank_of(agent), agent.name)))

    def one_of_level(self, level: Level) -> Agent:
        found = self.by_level(level)
        if len(found) != 1:
            raise ValueError(
                f"level {level.value} is served by {len(found)} agents: "
                f"the invocation order within the step is ambiguous"
            )
        return found[0]

    def call_order(self) -> tuple[Agent, ...]:
        ordered: list[Agent] = []
        for level in LEVEL_ORDER:
            ordered.extend(self.by_level(level))
        return tuple(ordered)


DEFAULT_AGENTS: tuple[Agent, ...] = (
    FieldCoordinator(),
    GroupAllocator(),
    WellExecutor(),
)

DEFAULT_REGISTRY = AgentRegistry(agents=DEFAULT_AGENTS)


def with_agents(registry: AgentRegistry, *added: Agent) -> AgentRegistry:
    if not added:
        raise ValueError(
            "extending the registry with not a single agent: what exactly is being added "
            "is not declared"
        )
    return AgentRegistry(agents=registry.agents + added)


WATER_AGENTS: tuple[Agent, ...] = DEFAULT_AGENTS + (WaterAgent(),)

WATER_REGISTRY = AgentRegistry(agents=WATER_AGENTS)

PRESSURE_AGENTS: tuple[Agent, ...] = WATER_AGENTS + (PressureAgent(),)

PRESSURE_REGISTRY = AgentRegistry(agents=PRESSURE_AGENTS)

__all__ = [
    "DEFAULT_AGENTS",
    "DEFAULT_RANK",
    "DEFAULT_REGISTRY",
    "LEVEL_ORDER",
    "PRESSURE_AGENTS",
    "PRESSURE_REGISTRY",
    "WATER_AGENTS",
    "WATER_REGISTRY",
    "AgentRegistry",
    "rank_of",
    "with_agents",
]
