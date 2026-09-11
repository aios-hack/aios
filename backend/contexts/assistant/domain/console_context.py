from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_LANG = "ru"


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


__all__ = ["DEFAULT_LANG", "ConsoleContext"]
