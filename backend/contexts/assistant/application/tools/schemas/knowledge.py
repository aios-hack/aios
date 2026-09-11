from __future__ import annotations

from backend.contexts.assistant.application.tools.schemas.base import (
    ToolDefinition,
    obj,
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
