from __future__ import annotations

from backend.contexts.assistant.application.tools.schemas.base import (
    ToolDefinition,
    obj,
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
