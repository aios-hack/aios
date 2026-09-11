from __future__ import annotations

from backend.contexts.assistant.application.tools.schemas.base import (
    SERIES_METRICS,
    ToolDefinition,
    obj,
)


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
