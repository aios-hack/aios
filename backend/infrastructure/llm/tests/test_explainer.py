from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.core.contracts import Rule, TraceEntry
from backend.infrastructure.llm.explainer import (
    build_explanation_prompt,
    explain,
    explain_decision,
    export_explanations_json,
)
from backend.infrastructure.llm.tests.conftest import INJECTOR, PRODUCER, make_artifact


def test_explain_decision_reconstructs_facts(schedule, trace_entry) -> None:
    explanation = explain_decision(
        [trace_entry], trace_entry.well, trace_entry.control_step, schedule
    )
    assert explanation.well == PRODUCER
    assert explanation.control_step == 3
    assert explanation.rule == "R2"
    assert explanation.inputs == {"watercut": 0.87, "liquid_rate": 72.5}
    assert explanation.decision == "SET_LRAT 45.5"
    assert "R2" in explanation.why
    assert "добывающая" in explanation.why
    assert trace_entry.decision in explanation.why


def test_explain_decision_without_trace_entry_raises(schedule, trace_entry) -> None:
    with pytest.raises(LookupError):
        explain_decision([trace_entry], INJECTOR, 0, schedule)
    with pytest.raises(LookupError):
        explain_decision([], PRODUCER, 3, schedule)


def test_prompt_instructs_cause_and_forbids_new_numbers(schedule, trace_entry) -> None:
    explanation = explain_decision(
        [trace_entry], trace_entry.well, trace_entry.control_step, schedule
    )
    prompt = build_explanation_prompt(explanation)
    assert "причинно-следственную" in prompt
    assert "правило" in prompt
    assert "выдумывать" in prompt
    assert "промысла" in prompt


def test_prompt_numbers_come_only_from_trace(schedule, trace_entry) -> None:
    explanation = explain_decision(
        [trace_entry], trace_entry.well, trace_entry.control_step, schedule
    )
    prompt = build_explanation_prompt(explanation)
    for value in trace_entry.inputs.values():
        assert str(value) in prompt
    allowed: set[str] = set()
    for value in trace_entry.inputs.values():
        allowed.update(re.findall(r"\d+(?:\.\d+)?", str(value)))
    allowed.update(re.findall(r"\d+(?:\.\d+)?", trace_entry.decision))
    allowed.update(re.findall(r"\d+(?:\.\d+)?", trace_entry.rule.value))
    allowed.add(str(trace_entry.control_step))
    tokens = set(re.findall(r"\d+(?:\.\d+)?", prompt))
    assert tokens <= allowed


class _FakeClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "объяснение решения"


def test_explain_sends_prompt_and_returns_text(schedule, trace_entry) -> None:
    client = _FakeClient()
    text = explain(
        [trace_entry], trace_entry.well, trace_entry.control_step, schedule, client
    )
    assert text == "объяснение решения"
    explanation = explain_decision(
        [trace_entry], trace_entry.well, trace_entry.control_step, schedule
    )
    assert client.prompts == [build_explanation_prompt(explanation)]


def test_export_without_client_writes_deterministic_parts(
    tmp_path: Path, trace_entry
) -> None:
    second = TraceEntry(
        control_step=1,
        well=INJECTOR,
        rule=Rule.R4,
        inputs={"injection_rate": 160.0},
        decision="SET_RATE 160.0",
    )
    artifact = make_artifact(trace=(trace_entry, second))
    out = tmp_path / "explanations.json"
    result = export_explanations_json(artifact, out)
    assert result == out
    items = json.loads(out.read_text(encoding="utf-8"))
    assert len(items) == 2
    by_well = {item["well"]: item for item in items}
    assert by_well[PRODUCER]["rule"] == "R2"
    assert by_well[PRODUCER]["inputs"] == {"watercut": 0.87, "liquid_rate": 72.5}
    assert by_well[PRODUCER]["decision"] == "SET_LRAT 45.5"
    assert by_well[INJECTOR]["rule"] == "R4"
    for item in items:
        assert item["text"] is None
        assert item["why"]


def test_export_with_client_fills_text(tmp_path: Path, trace_entry) -> None:
    artifact = make_artifact(trace=(trace_entry,))
    out = tmp_path / "explanations.json"
    export_explanations_json(artifact, out, client=_FakeClient())
    items = json.loads(out.read_text(encoding="utf-8"))
    assert items[0]["text"] == "объяснение решения"
