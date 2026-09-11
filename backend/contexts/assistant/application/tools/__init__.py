from __future__ import annotations

from typing import Any, Callable, Mapping

from backend.contexts.assistant.application.tools import (
    cases,
    connectivity as connectivity_module,
    council,
    decisions,
    docs,
    fields,
    knowledge as knowledge_module,
    patterns,
    ranking,
    rules,
    run_history as run_history_module,
    runs,
    scenarios,
    system as system_module,
    wells,
)
from backend.contexts.assistant.application.tools.actions import build_action
from backend.contexts.assistant.application.tools.context import Card, ToolContext, ToolFailure
from backend.contexts.assistant.application.tools.decisions import NoTraceEntry
from backend.contexts.assistant.application.tools.labels import title
from backend.contexts.assistant.application.tools.registry import (
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
    "run_status": runs.run_status,
    "submission_summary": runs.submission_summary,
    "search_docs": docs.search_docs,
    "system_map": system_module.system_map,
    "system_status": system_module.system_status,
    "run_history": run_history_module.run_history,
    "run_detail": run_history_module.run_detail,
    "compare_runs": run_history_module.compare_runs,
    "case_constraints": cases.case_constraints,
    "council_step": council.council_step,
    "physics_report": run_history_module.physics_report,
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
