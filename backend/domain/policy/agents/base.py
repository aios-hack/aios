"""Протокол агента и предложение, которое агент кладёт на стол.

Агенты предлагают, проекция на жёсткие ограничения отсекает, OPM решает.
Ни один агент не пишет уставку в расписание сам.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backend.core.contracts import ControlEvent, Rule

from backend.domain.policy.levels import Level, LeveledTraceEntry
from backend.domain.policy.state import PolicyState, RuleContext


@dataclass(frozen=True, slots=True)
class Proposal:
    level: Level
    agent: str
    decisions: tuple[ControlEvent, ...]
    rule_by_decision: tuple[Rule, ...]
    trace: tuple[LeveledTraceEntry, ...]

    def __post_init__(self) -> None:
        if not self.agent:
            raise ValueError("предложение без имени агента: автора не восстановить")
        if len(self.decisions) != len(self.rule_by_decision):
            raise ValueError(
                f"{self.agent}: {len(self.decisions)} решений при "
                f"{len(self.rule_by_decision)} правилах — авторство решения "
                f"не восстановимо"
            )
        for leveled in self.trace:
            if leveled.level is not self.level:
                raise ValueError(
                    f"{self.agent}: запись уровня {leveled.level.value} в "
                    f"предложении уровня {self.level.value}"
                )


@runtime_checkable
class Agent(Protocol):
    name: str
    level: Level
    responsibilities: tuple[str, ...]

    def propose(self, state: PolicyState, context: RuleContext) -> Proposal: ...
