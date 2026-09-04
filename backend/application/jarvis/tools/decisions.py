"""Journal facts for a well at a control step, read straight from trace.json."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.application.jarvis.artifacts import ArtifactError, ScenarioIndex
from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure
from backend.application.jarvis.tools.labels import RULE_NAMES, pick, title
from backend.application.jarvis.tools.registry import NO_TRACE_ENTRY
from backend.application.jarvis.tools.rules import rule_statement

TRACE_META_KEY = "__meta__"


class NoTraceEntry(ToolFailure):
    code = NO_TRACE_ENTRY


def _trace_provenance(index: ScenarioIndex) -> str:
    meta = index.trace.get(TRACE_META_KEY)
    if isinstance(meta, Mapping):
        value = meta.get("provenance")
        if isinstance(value, str):
            return value
    return index.provenance()


def _records(index: ScenarioIndex, well: str, step: int) -> Sequence[Mapping[str, Any]]:
    by_step = index.trace.get(well)
    if not isinstance(by_step, Mapping):
        raise NoTraceEntry(
            f"{NO_TRACE_ENTRY}: the journal of scenario {index.scenario} holds no "
            f"records for well {well}, so there is nothing to explain and nothing "
            "may be invented in their place"
        )
    found = by_step.get(str(step))
    if found is None:
        found = by_step.get(step)
    if not isinstance(found, Sequence) or isinstance(found, (str, bytes)) or not found:
        known = sorted((int(key) for key in by_step if str(key).isdigit()))
        listed = ", ".join(str(value) for value in known[:12]) if known else "none"
        raise NoTraceEntry(
            f"{NO_TRACE_ENTRY}: well {well} has no journal record at control step "
            f"{step} in scenario {index.scenario}: the journal covers the steps "
            f"{listed}. No rule fired there, so no explanation exists"
        )
    return found


def _fact(record: Mapping[str, Any], lang: str, well: str, step: int) -> dict[str, Any]:
    rule = record.get("rule")
    if not isinstance(rule, str) or not rule:
        raise NoTraceEntry(
            f"{NO_TRACE_ENTRY}: a journal record of well {well} at step {step} "
            "carries no rule, so the decision cannot be attributed"
        )
    decision = record.get("decision")
    if not isinstance(decision, str) or not decision:
        raise NoTraceEntry(
            f"{NO_TRACE_ENTRY}: the record of rule {rule} for well {well} at step "
            f"{step} carries no decision, so there is nothing to report"
        )
    raw = record.get("inputs")
    inputs: dict[str, float] = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            inputs[str(key)] = float(value)
    return {
        "rule": rule,
        "name": pick(RULE_NAMES, rule, lang),
        "statement": rule_statement(rule),
        "inputs": inputs,
        "decision": decision,
    }


def explain_decision(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    well = str(arguments["well"])
    step = int(arguments["step"])
    try:
        index = context.index()
        index.require_well(well)
        index.require_step(step)
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    records = _records(index, well, step)
    facts = [_fact(record, context.lang, well, step) for record in records]
    head = facts[0]
    payload: dict[str, Any] = {
        "well": well,
        "step": step,
        "date": index.dates[step],
        "rule": head["rule"],
        "name": head["name"],
        "statement": head["statement"],
        "inputs": head["inputs"],
        "decision": head["decision"],
        "why": None,
        "facts": facts,
        "source": "trace.json",
    }
    return Card(
        type="rule",
        title=title("rule", context.lang, rule=head["rule"], well=well),
        payload=payload,
        provenance=_trace_provenance(index),
    )
