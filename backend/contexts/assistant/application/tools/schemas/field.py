from __future__ import annotations

from backend.contexts.assistant.application.tools.schemas.base import (
    CONNECTIVITY_LIMIT,
    EVENT_TYPES,
    RANK_LIMIT,
    RANK_METRICS,
    ToolDefinition,
    obj,
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
