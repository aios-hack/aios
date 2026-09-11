from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SERIES_METRICS: tuple[str, ...] = (
    "liquid_rate",
    "injection_rate",
    "watercut",
    "bhp",
)


RANK_METRICS: tuple[str, ...] = (
    "npv",
    "watercut",
    "liquid_rate",
    "injection_rate",
)


EVENT_TYPES: tuple[str, ...] = ("COMMISSIONED", "ROLE_CHANGE", "SHUT")


RANK_LIMIT = 10


CONNECTIVITY_LIMIT = 12


DOC_HITS = 6


DOC_SCOPES: tuple[str, ...] = ("docs", "knowledge", "all")


RUN_LIMIT = 10


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    schema: Mapping[str, Any]
    card_type: str


def obj(properties: Mapping[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }
