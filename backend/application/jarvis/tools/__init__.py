from __future__ import annotations

from typing import Any, Callable, Mapping

from backend.application.jarvis.tools import (
    connectivity as connectivity_module,
    decisions,
    fields,
    knowledge as knowledge_module,
    patterns,
    ranking,
    rules,
    scenarios,
    wells,
)
from backend.application.jarvis.tools.actions import build_action
from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure
from backend.application.jarvis.tools.decisions import NoTraceEntry
from backend.application.jarvis.tools.labels import title
from backend.application.jarvis.tools.registry import (
    JOURNAL_TOOL,
    NO_TRACE_ENTRY,
    ToolInputError,
    definition,
    tool_specs,
    validate_arguments,
)

ToolFn = Callable[[ToolContext, Mapping[str, Any]], Card]

HANDLERS: Mapping[str, ToolFn] = {
    "well_snapshot": wells.well_snapshot,
    "well_series": wells.well_series,
    "field_metrics": fields.field_metrics,
    "field_events": fields.field_events,
    "explain_decision": rules.explain_decision,
    "decision_journal": decisions.explain_decision,
    "rank_wells": ranking.rank_wells,
    "rule_impact": rules.rule_impact,
    "connectivity": connectivity_module.connectivity,
    "compare_scenarios": scenarios.compare_scenarios,
    "find_patterns": patterns.find_patterns,
    "explain_term": knowledge_module.explain_term,
    "platform_guide": knowledge_module.platform_guide,
}


def run_tool(
    name: str, context: ToolContext, arguments: Mapping[str, Any]
) -> Card:
    handler = HANDLERS.get(name)
    if handler is None:
        raise ToolFailure(
            f"Jarvis has no tool named {name}: available tools are "
            f"{', '.join(sorted(HANDLERS))}"
        )
    checked = validate_arguments(name, arguments)
    card = handler(context, checked)
    action = build_action(card.type, card.payload, context.scenario_name)
    if action is None:
        return card
    return Card(
        type=card.type,
        title=card.title,
        payload=card.payload,
        provenance=card.provenance,
        action=action,
    )


def error_card(name: str, message: str, lang: str = "ru") -> Card:
    try:
        card_type = definition(name).card_type
    except ToolInputError:
        card_type = "error"
    return Card(
        type="error",
        title=title("tool_failed", lang, tool=name),
        payload={"tool": name, "message": message, "expected_card": card_type},
        provenance="none",
    )


__all__ = [
    "Card",
    "HANDLERS",
    "JOURNAL_TOOL",
    "NO_TRACE_ENTRY",
    "NoTraceEntry",
    "ToolContext",
    "ToolFailure",
    "ToolInputError",
    "error_card",
    "run_tool",
    "tool_specs",
]
