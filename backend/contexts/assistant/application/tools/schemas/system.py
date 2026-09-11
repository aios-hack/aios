from __future__ import annotations

from backend.contexts.assistant.application.tools.schemas.base import (
    DOC_HITS,
    DOC_SCOPES,
    RUN_LIMIT,
    ToolDefinition,
    obj,
)


SYSTEM_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="search_docs",
        description=(
            "Full-text search over the project documents and the curated "
            "knowledge base: the task statement, the architecture, the plans, "
            "the jury answers, the glossary and the screen guide. Returns "
            "sections with their headings, anchors and snippets, so an answer "
            "quotes a document instead of retelling it from memory. Use it for "
            "how to run something, what a file is, why a decision was taken, "
            "and whenever the curated base misses a term."
        ),
        schema=obj(
            {
                "query": {
                    "type": "string",
                    "description": "words from the question, in the question's language",
                },
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": DOC_HITS,
                    "description": "how many sections to return",
                },
                "scope": {"type": "string", "enum": list(DOC_SCOPES)},
            },
            ("query",),
        ),
        card_type="doc",
    ),
    ToolDefinition(
        name="system_map",
        description=(
            "The map of the AIOS platform: components, what each of them does "
            "and how data flows between them. Without a focus the whole map is "
            "returned; with a focus only that node and its neighbourhood."
        ),
        schema=obj(
            {
                "focus": {
                    "type": "string",
                    "description": "node identifier or its name, e.g. opm, surrogate, jarvis",
                },
                "depth": {"type": "integer", "minimum": 1, "maximum": 2},
            }
        ),
        card_type="system-map",
    ),
    ToolDefinition(
        name="system_status",
        description=(
            "The current state of the system: the pinned OPM champion, the "
            "latest run with its status and NPV, the scenario and step in the "
            "console, and the diagnostic alerts of that step. Reports a value "
            "that was never recorded as not recorded, never as zero."
        ),
        schema=obj({}),
        card_type="status-board",
    ),
    ToolDefinition(
        name="run_history",
        description=(
            "The list of calculation runs, newest first: status, predicted and "
            "verified NPV, soundness, search strategy and seed, read from the "
            "manifests in the run directories."
        ),
        schema=obj(
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": RUN_LIMIT},
                "status": {"type": "string"},
            }
        ),
        card_type="run-list",
    ),
    ToolDefinition(
        name="run_detail",
        description=(
            "One run in full: manifest, provenance, validation, the constraints "
            "report, the physics report and the submission package. Without "
            "run_id the latest run is read."
        ),
        schema=obj({"run_id": {"type": "string"}}),
        card_type="run",
    ),
    ToolDefinition(
        name="compare_runs",
        description=(
            "Two runs side by side: NPV, status, soundness and constraints. "
            "Without arguments the two newest runs are compared."
        ),
        schema=obj({"a": {"type": "string"}, "b": {"type": "string"}}),
        card_type="compare",
    ),
    ToolDefinition(
        name="case_constraints",
        description=(
            "The constraints of a case: injection and liquid limits, production "
            "floors, well outages and the infrastructure limits, each value with "
            "its source. Without a case the competition constraints are read."
        ),
        schema=obj({"case": {"type": "string"}}),
        card_type="constraints",
    ),
    ToolDefinition(
        name="council_step",
        description=(
            "The decisions of the agent council at a control step: what the "
            "field coordinator allocated, how the group allocator split its "
            "quota and which rule the well executor applied to each well. The "
            "step comes from the console context by default."
        ),
        schema=obj(
            {
                "step": {"type": "integer"},
                "group": {"type": "string"},
                "well": {"type": "string"},
            }
        ),
        card_type="council",
    ),
    ToolDefinition(
        name="physics_report",
        description=(
            "The physics report of a run: whether the response is admissible "
            "and which of the seven invariants passed, warned or blocked. A "
            "skipped invariant counts as a failed invariant, never as a passed "
            "one. Without run_id the latest run is read."
        ),
        schema=obj({"run_id": {"type": "string"}}),
        card_type="physics",
    ),
)
