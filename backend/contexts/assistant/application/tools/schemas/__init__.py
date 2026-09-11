from __future__ import annotations

from backend.contexts.assistant.application.tools.schemas.base import (
    CONNECTIVITY_LIMIT,
    DOC_HITS,
    DOC_SCOPES,
    EVENT_TYPES,
    RANK_LIMIT,
    RANK_METRICS,
    RUN_LIMIT,
    SERIES_METRICS,
    ToolDefinition,
    obj,
)
from backend.contexts.assistant.application.tools.schemas.decisions import DECISION_TOOLS
from backend.contexts.assistant.application.tools.schemas.field import FIELD_TOOLS
from backend.contexts.assistant.application.tools.schemas.knowledge import KNOWLEDGE_TOOLS
from backend.contexts.assistant.application.tools.schemas.runs import RUN_TOOLS
from backend.contexts.assistant.application.tools.schemas.system import SYSTEM_TOOLS
from backend.contexts.assistant.application.tools.schemas.wells import WELL_TOOLS

DEFINITIONS: tuple[ToolDefinition, ...] = (
    *WELL_TOOLS,
    *FIELD_TOOLS,
    *DECISION_TOOLS,
    *KNOWLEDGE_TOOLS,
    *RUN_TOOLS,
    *SYSTEM_TOOLS,
)

__all__ = [
    "CONNECTIVITY_LIMIT",
    "DECISION_TOOLS",
    "DEFINITIONS",
    "DOC_HITS",
    "DOC_SCOPES",
    "EVENT_TYPES",
    "FIELD_TOOLS",
    "KNOWLEDGE_TOOLS",
    "RANK_LIMIT",
    "RANK_METRICS",
    "RUN_LIMIT",
    "RUN_TOOLS",
    "SERIES_METRICS",
    "SYSTEM_TOOLS",
    "ToolDefinition",
    "WELL_TOOLS",
    "obj",
]
