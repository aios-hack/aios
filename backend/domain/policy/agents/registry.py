"""Реестр агентов и порядок их вызова на шаге управления.

Точка расширения: новый агент — новый файл, реализующий `Agent`, плюс
строка в `AGENTS`. Ядро иерархии при этом не меняется.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.policy.agents.base import Agent
from backend.domain.policy.agents.field import FieldCoordinator
from backend.domain.policy.agents.group import GroupAllocator
from backend.domain.policy.agents.well import WellExecutor
from backend.domain.policy.levels import Level

LEVEL_ORDER: tuple[Level, ...] = (Level.FIELD, Level.GROUP, Level.WELL)


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    agents: tuple[Agent, ...]

    def __post_init__(self) -> None:
        if not self.agents:
            raise ValueError("реестр агентов пуст: шаг иерархии некому исполнить")
        seen: set[str] = set()
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

    def names(self) -> tuple[str, ...]:
        return tuple(agent.name for agent in self.agents)

    def of(self, name: str) -> Agent:
        for agent in self.agents:
            if agent.name == name:
                return agent
        raise ValueError(f"агента {name} нет в реестре")

    def by_level(self, level: Level) -> tuple[Agent, ...]:
        return tuple(agent for agent in self.agents if agent.level is level)

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
