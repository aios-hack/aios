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


WELL_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="well_snapshot",
        description=(
            "Snapshot of one well at a control step: role, status, liquid rate, "
            "injection, water cut, bottomhole pressure, NPV and a rate sparkline."
        ),
        schema=obj(
            {
                "well": {"type": "string", "description": "well identifier"},
                "step": {
                    "type": "integer",
                    "description": "control step 0-224; taken from the console context by default",
                },
            },
            ("well",),
        ),
        card_type="well",
    ),
    ToolDefinition(
        name="well_series",
        description=(
            "A series of one value for a well over a step interval: liquid rate, "
            "injection, water cut or bottomhole pressure."
        ),
        schema=obj(
            {
                "well": {"type": "string"},
                "metric": {"type": "string", "enum": list(SERIES_METRICS)},
                "from_step": {"type": "integer"},
                "to_step": {"type": "integer"},
                "window": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "highlight interval [from, to] inside the series",
                },
            },
            ("well", "metric"),
        ),
        card_type="series",
    ),
)

FIELD_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="field_metrics",
        description=(
            "Field summary at a step: active wells, production, injection, "
            "compensation and cumulative NPV."
        ),
        schema=obj({"step": {"type": "integer"}}),
        card_type="metric",
    ),
    ToolDefinition(
        name="field_events",
        description=(
            "Field events over a step interval: a well commissioned, converted to "
            "injection, or shut in."
        ),
        schema=obj(
            {
                "from_step": {"type": "integer"},
                "to_step": {"type": "integer"},
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(EVENT_TYPES)},
                },
            }
        ),
        card_type="event-strip",
    ),
    ToolDefinition(
        name="rank_wells",
        description=(
            "Ranking of wells by NPV, water cut, liquid rate or injection."
        ),
        schema=obj(
            {
                "by": {"type": "string", "enum": list(RANK_METRICS)},
                "order": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": RANK_LIMIT},
                "step": {"type": "integer"},
            },
            ("by",),
        ),
        card_type="well-list",
    ),
    ToolDefinition(
        name="connectivity",
        description=(
            "A well's links by the measured influence matrix: neighbours, link "
            "weights and the highlight for the field map."
        ),
        schema=obj(
            {
                "well": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": CONNECTIVITY_LIMIT,
                },
                "min_weight": {"type": "number"},
            },
            ("well",),
        ),
        card_type="field-map",
    ),
    ToolDefinition(
        name="find_patterns",
        description=(
            "Diagnostic findings across the field: injection without response, "
            "water cut rising without oil, bottomhole pressure dropping."
        ),
        schema=obj(
            {
                "well": {"type": "string"},
                "pattern": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": RANK_LIMIT},
            }
        ),
        card_type="pattern",
    ),
)

DECISION_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="explain_decision",
        description=(
            "Why the system took a decision for a well at a step: the rule that "
            "fired, its actual inputs and the decision."
        ),
        schema=obj(
            {"well": {"type": "string"}, "step": {"type": "integer"}},
            ("well", "step"),
        ),
        card_type="rule",
    ),
    ToolDefinition(
        name="decision_journal",
        description=(
            "The journal facts recorded for a well at a control step: every rule "
            "that fired, its recorded inputs and its decision, read straight from "
            "the trace of the run. Refuses with no-trace-entry when the journal "
            "holds no record for that well and step."
        ),
        schema=obj(
            {"well": {"type": "string"}, "step": {"type": "integer"}},
            ("well", "step"),
        ),
        card_type="rule",
    ),
    ToolDefinition(
        name="rule_impact",
        description=(
            "The contribution of rules R0 to R7 to NPV by ablation: delta, share "
            "and whether the contribution was measured at all."
        ),
        schema=obj({"rule": {"type": "string"}}),
        card_type="rule",
    ),
    ToolDefinition(
        name="compare_scenarios",
        description=(
            "Comparison of two scenarios: NPV, constraints, status and the wells "
            "with the largest difference."
        ),
        schema=obj({"a": {"type": "string"}, "b": {"type": "string"}}, ("a", "b")),
        card_type="compare",
    ),
)

KNOWLEDGE_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="explain_term",
        description=(
            "A domain term from the curated knowledge base: definition, formula, "
            "unit, source and where it lives in the platform."
        ),
        schema=obj(
            {
                "query": {"type": "string"},
                "lang": {"type": "string", "enum": ["ru", "en"]},
            },
            ("query",),
        ),
        card_type="glossary",
    ),
    ToolDefinition(
        name="platform_guide",
        description=(
            "Guidance on a platform screen: what it shows, how to read it and its "
            "key controls."
        ),
        schema=obj(
            {
                "query": {"type": "string"},
                "workspace": {"type": "string"},
                "view": {"type": "string"},
                "lang": {"type": "string", "enum": ["ru", "en"]},
            }
        ),
        card_type="guide",
    ),
)

DEFINITIONS: tuple[ToolDefinition, ...] = (
    *WELL_TOOLS,
    *FIELD_TOOLS,
    *DECISION_TOOLS,
    *KNOWLEDGE_TOOLS,
)
