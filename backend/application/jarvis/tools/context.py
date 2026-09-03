from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.application.jarvis.artifacts import ArtifactStore, ScenarioIndex

DEFAULT_LANG = "ru"


class ToolFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ConsoleContext:
    scenario: str = "base"
    step: int | None = None
    date: str | None = None
    selected_well: str | None = None
    workspace: str | None = None
    view: str | None = None
    lang: str = DEFAULT_LANG

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "step": self.step,
            "date": self.date,
            "selected_well": self.selected_well,
            "workspace": self.workspace,
            "view": self.view,
        }


@dataclass(frozen=True, slots=True)
class ToolContext:
    store: ArtifactStore
    console: ConsoleContext = field(default_factory=ConsoleContext)
    knowledge: Any = None

    @property
    def scenario_name(self) -> str:
        return self.console.scenario or "base"

    def index(self, scenario: str | None = None) -> ScenarioIndex:
        return self.store.scenario(scenario or self.scenario_name)

    def resolve_step(self, requested: int | None) -> int:
        index = self.index()
        if requested is not None:
            index.require_step(requested)
            return requested
        if self.console.step is not None:
            index.require_step(self.console.step)
            return self.console.step
        if self.console.date is not None:
            return index.step_for_date(self.console.date)
        return index.step_count() - 1

    @property
    def lang(self) -> str:
        return self.console.lang or DEFAULT_LANG


@dataclass(frozen=True, slots=True)
class Card:
    type: str
    title: str
    payload: Mapping[str, Any]
    provenance: str
    action: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "payload": dict(self.payload),
            "provenance": self.provenance,
        }
        if self.action is not None:
            body["action"] = dict(self.action)
        return body
