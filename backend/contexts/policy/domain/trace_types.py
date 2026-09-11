from __future__ import annotations

from dataclasses import (
    dataclass,
)
from enum import Enum
from backend.contexts.policy.domain.policy import Rule, TraceEntry
from backend.contexts.policy.domain.flags import (
    RuleFlags,
)
from backend.contexts.policy.domain.trace import RunTrace


class Level(Enum):
    FIELD = "FIELD"
    GROUP = "GROUP"
    WELL = "WELL"


@dataclass(frozen=True, slots=True)
class LeveledTraceEntry:
    level: Level
    agent: str
    entry: TraceEntry

    def __post_init__(self) -> None:
        if not self.agent:
            raise ValueError("a Trace entry without an agent name: the level cannot be recovered")
        if not self.entry.inputs:
            raise ValueError(
                f"{self.level.value}/{self.agent}: a Trace entry without input numbers"
            )


@dataclass(frozen=True, slots=True)
class HierarchyTrace:
    entries: tuple[LeveledTraceEntry, ...]
    flags: RuleFlags

    def __post_init__(self) -> None:
        for leveled in self.entries:
            if not self.flags.is_on(leveled.entry.rule):
                raise ValueError(
                    f"{leveled.entry.rule.value} is disabled by a flag yet left "
                    f"an entry of level {leveled.level.value} for agent "
                    f"{leveled.agent}"
                )

    def __len__(self) -> int:
        return len(self.entries)

    def by_level(self, level: Level) -> tuple[LeveledTraceEntry, ...]:
        return tuple(e for e in self.entries if e.level is level)

    def by_agent(self, agent: str) -> tuple[LeveledTraceEntry, ...]:
        return tuple(e for e in self.entries if e.agent == agent)

    def levels_present(self) -> tuple[Level, ...]:
        seen = {e.level for e in self.entries}
        return tuple(level for level in Level if level in seen)

    def count_by_level(self) -> dict[Level, int]:
        counted = {level: 0 for level in Level}
        for leveled in self.entries:
            counted[leveled.level] += 1
        return counted

    def as_run_trace(self) -> RunTrace:
        return RunTrace(
            entries=tuple(e.entry for e in self.entries), flags=self.flags
        )

    def by_rule(self, rule: Rule) -> tuple[LeveledTraceEntry, ...]:
        return tuple(e for e in self.entries if e.entry.rule is rule)

    def levels_of(self, well: str) -> tuple[Level, ...]:
        seen = {e.level for e in self.entries if e.entry.well == well}
        return tuple(level for level in Level if level in seen)


__all__ = [
    "HierarchyTrace",
    "Level",
    "LeveledTraceEntry",
]
