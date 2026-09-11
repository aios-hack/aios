from __future__ import annotations

from typing import Literal, NewType

Lang = Literal["ru", "en"]
WellId = NewType("WellId", str)
GroupId = NewType("GroupId", str)
ControlStep = NewType("ControlStep", int)
RunId = NewType("RunId", str)
ScenarioId = NewType("ScenarioId", str)


def is_lang(value: object) -> bool:
    return value in ("ru", "en")


__all__ = [
    "ControlStep",
    "GroupId",
    "Lang",
    "RunId",
    "ScenarioId",
    "WellId",
    "is_lang",
]
