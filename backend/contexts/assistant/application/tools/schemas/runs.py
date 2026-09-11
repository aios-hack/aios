from __future__ import annotations

from backend.contexts.assistant.application.tools.schemas.base import (
    ToolDefinition,
    obj,
)


RUN_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="run_status",
        description=(
            "The recorded state of a calculation run read from its manifest: "
            "status, predicted and verified NPV, soundness, dynamic violations "
            "and the search strategy. Answers with the numbers the manifest "
            "holds and reports a field the manifest never recorded as not "
            "recorded, never as zero. Without run_id the latest run is read."
        ),
        schema=obj(
            {
                "run_id": {
                    "type": "string",
                    "description": "run directory name; the latest run by default",
                }
            }
        ),
        card_type="run-status",
    ),
    ToolDefinition(
        name="submission_summary",
        description=(
            "The submission package of a run: claimed NPV in roubles, the "
            "canonical schedule and content hashes, the deck, constraints, "
            "economics and methodology hashes, the OPM image and the git "
            "commit, all read from submission/claimed_npv.json, plus whether "
            "the package files are in place. Says plainly that no package was "
            "assembled when the run has none."
        ),
        schema=obj(
            {
                "run_id": {
                    "type": "string",
                    "description": "run directory name; the latest run by default",
                }
            }
        ),
        card_type="submission",
    ),
)
