from __future__ import annotations

import pytest

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.tools import run_tool, tool_specs
from backend.application.jarvis.tools.context import (
    ConsoleContext,
    ToolContext,
    ToolFailure,
)
from backend.application.jarvis.tools.decisions import NoTraceEntry
from backend.application.jarvis.tools.registry import JOURNAL_TOOL, NO_TRACE_ENTRY

WITH_TRACE = "whatif-injection-cut"


def make(store: ArtifactStore, **console: object) -> ToolContext:
    return ToolContext(store=store, console=ConsoleContext(**console))


def test_journal_tool_is_registered() -> None:
    assert JOURNAL_TOOL in {spec.name for spec in tool_specs()}


def test_journal_returns_recorded_facts(store: ArtifactStore) -> None:
    card = run_tool(
        JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "13", "step": 10}
    )
    assert card.type == "rule"
    assert card.payload["well"] == "13"
    assert card.payload["step"] == 10
    assert card.payload["rule"] == "R1"
    assert card.payload["decision"] == "SET_LRAT 112.9"
    assert card.payload["inputs"] == {"liquid_rate": 112.9, "watercut": 0.614}
    assert card.payload["source"] == "trace.json"
    assert card.payload["statement"]


def test_journal_numbers_come_only_from_the_trace(store: ArtifactStore) -> None:
    store_index = store.scenario(WITH_TRACE)
    recorded = store_index.trace["13"]["10"]
    card = run_tool(
        JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "13", "step": 10}
    )
    for fact, source in zip(card.payload["facts"], recorded):
        assert fact["inputs"] == {
            key: float(value) for key, value in source["inputs"].items()
        }
        assert fact["decision"] == source["decision"]
        assert fact["rule"] == source["rule"]


def test_journal_carries_the_trace_provenance(store: ArtifactStore) -> None:
    card = run_tool(
        JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "13", "step": 10}
    )
    assert card.provenance == "synthetic-demo"


def test_journal_action_opens_the_rules_view(store: ArtifactStore) -> None:
    card = run_tool(
        JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "13", "step": 10}
    )
    assert card.action["workspace"] == "decisions"
    assert card.action["view"] == "rules"
    assert card.action["well"] == "13"
    assert card.action["step"] == 10
    assert card.action["scenario"] == WITH_TRACE


def test_journal_refuses_a_step_without_a_record(store: ArtifactStore) -> None:
    with pytest.raises(NoTraceEntry) as error:
        run_tool(
            JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "13", "step": 11}
        )
    assert NO_TRACE_ENTRY in str(error.value)
    assert error.value.code == NO_TRACE_ENTRY


def test_journal_refuses_a_well_without_records(store: ArtifactStore) -> None:
    with pytest.raises(NoTraceEntry) as error:
        run_tool(JOURNAL_TOOL, make(store), {"well": "13", "step": 10})
    assert NO_TRACE_ENTRY in str(error.value)


def test_no_trace_entry_is_a_tool_failure(store: ArtifactStore) -> None:
    with pytest.raises(ToolFailure):
        run_tool(
            JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "13", "step": 11}
        )


def test_journal_refuses_an_unknown_well(store: ArtifactStore) -> None:
    with pytest.raises(ToolFailure) as error:
        run_tool(
            JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "9999", "step": 10}
        )
    assert NO_TRACE_ENTRY not in str(error.value)


def test_journal_refuses_a_step_outside_the_horizon(store: ArtifactStore) -> None:
    with pytest.raises(ToolFailure):
        run_tool(
            JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "13", "step": 9999}
        )


def test_journal_requires_both_arguments(store: ArtifactStore) -> None:
    with pytest.raises(Exception):
        run_tool(JOURNAL_TOOL, make(store, scenario=WITH_TRACE), {"well": "13"})
