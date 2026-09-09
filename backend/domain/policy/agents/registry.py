from __future__ import annotations

from dataclasses import dataclass

from backend.domain.policy.agents.base import DEFAULT_RANK, Agent
from backend.domain.policy.agents.field import FieldCoordinator
from backend.domain.policy.agents.group import GroupAllocator
from backend.domain.policy.agents.pressure import PressureAgent
from backend.domain.policy.agents.water import WaterAgent
from backend.domain.policy.agents.well import WellExecutor
from backend.domain.policy.levels import Level

LEVEL_ORDER: tuple[Level, ...] = (Level.FIELD, Level.GROUP, Level.WELL)


def rank_of(agent: Agent) -> int:
    rank = getattr(agent, "rank", DEFAULT_RANK)
    if not isinstance(rank, int) or isinstance(rank, bool):
        raise ValueError(
            f"{getattr(agent, 'name', '<без имени>')}: rank={rank!r} не целое "
            f"число — порядок вызова не сравним"
        )
    return rank


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    agents: tuple[Agent, ...]

    def __post_init__(self) -> None:
        if not self.agents:
            raise ValueError("реестр агентов пуст: шаг иерархии некому исполнить")
        seen: set[str] = set()
        ranks: dict[tuple[Level, int], str] = {}
        for agent in self.agents:
            if not agent.name:
                raise ValueError("агент без имени: реестр не адресуем")
            if agent.name in seen:
                raise ValueError(f"имя агента {agent.name} встречается дважды")
            seen.add(agent.name)
            if not agent.responsibilities:
                raise ValueError(
                    f"{agent.name}: агент без описанной ответственности — "
                    f"назвать его роль на защите будет нечем"
                )
            if agent.level not in LEVEL_ORDER:
                raise ValueError(f"{agent.name}: неизвестный уровень {agent.level}")
            slot = (agent.level, rank_of(agent))
            taken = ranks.get(slot)
            if taken is not None:
                raise ValueError(
                    f"{agent.name} и {taken} заявили ранг {slot[1]} на уровне "
                    f"{agent.level.value}: кто кого ограничивает — не определено"
                )
            ranks[slot] = agent.name

    def names(self) -> tuple[str, ...]:
        return tuple(agent.name for agent in self.agents)

    def of(self, name: str) -> Agent:
        for agent in self.agents:
            if agent.name == name:
                return agent
        raise ValueError(f"агента {name} нет в реестре")

    def by_level(self, level: Level) -> tuple[Agent, ...]:
        found = [agent for agent in self.agents if agent.level is level]
        return tuple(sorted(found, key=lambda agent: (rank_of(agent), agent.name)))

    def one_of_level(self, level: Level) -> Agent:
        found = self.by_level(level)
        if len(found) != 1:
            raise ValueError(
                f"уровень {level.value} обслуживают {len(found)} агентов: "
                f"порядок вызова на шаге неоднозначен"
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
            "расширение реестра без единого агента: что именно добавляется, "
            "не объявлено"
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
