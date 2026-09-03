from __future__ import annotations

from typing import Any, Mapping

from backend.core.contracts import (
    Availability,
    OperatingStatus,
    Role,
    Rule,
    Schedule,
    ScheduleMeta,
    TraceEntry,
    WellState,
)

from backend.application.jarvis.artifacts import ArtifactError, ScenarioIndex
from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure
from backend.application.jarvis.tools.labels import RULE_NAMES, pick, title
from backend.domain.policy.rules import ADMISSION_CRITERIA
from backend.infrastructure.llm.explainer import explain_decision as reconstruct

ROLES: Mapping[str, Role] = {
    "PROD": Role.PROD,
    "INJ": Role.INJ,
    "NONE": Role.NONE,
}
AVAILABILITY: Mapping[str, Availability] = {
    "AVAILABLE": Availability.AVAILABLE,
    "NOT_COMMISSIONED": Availability.NOT_COMMISSIONED,
}


def _trace_entries(index: ScenarioIndex) -> list[TraceEntry]:
    entries: list[TraceEntry] = []
    for well, by_step in index.trace.items():
        if well == "__meta__" or not isinstance(by_step, dict):
            continue
        for step, records in by_step.items():
            for record in records:
                entries.append(
                    TraceEntry(
                        control_step=int(step),
                        well=str(well),
                        rule=Rule(record["rule"]),
                        inputs=dict(record["inputs"]),
                        decision=str(record["decision"]),
                    )
                )
    return entries


def _schedule_from_step(index: ScenarioIndex, step: int) -> Schedule:
    state: dict[str, WellState] = {}
    for row in index.timeline["steps"][step]["wells"]:
        availability = AVAILABILITY.get(
            str(row["availability"]), Availability.NOT_COMMISSIONED
        )
        if availability is Availability.NOT_COMMISSIONED:
            state[str(row["well"])] = WellState(
                availability=availability,
                role=Role.NONE,
                operating_status=OperatingStatus.SHUT,
                setpoint=0.0,
            )
            continue
        state[str(row["well"])] = WellState(
            availability=availability,
            role=ROLES.get(str(row["role"]), Role.NONE),
            operating_status=(
                OperatingStatus.OPEN
                if str(row["operating_status"]) == "OPEN"
                else OperatingStatus.SHUT
            ),
            setpoint=float(row["setpoint"]),
        )
    return Schedule(
        meta=ScheduleMeta(
            wells=tuple(sorted(state)), provenance=index.provenance()
        ),
        initial_state=state,
        fixed_deck_events=(),
        control_events=(),
    )


def rule_statement(rule: str) -> str:
    try:
        return ADMISSION_CRITERIA[Rule(rule)]
    except (KeyError, ValueError) as error:
        raise ToolFailure(
            f"rule {rule} is not part of the policy: the policy defines R0 to R7"
        ) from error


def explain_decision(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    well = str(arguments["well"])
    step = int(arguments["step"])
    try:
        index = context.index()
        index.require_well(well)
        index.require_step(step)
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    entries = _trace_entries(index)
    if not entries:
        raise ToolFailure(
            f"scenario {index.scenario} carries no Trace records: there is "
            "nothing to reconstruct a decision from, an explanation is only "
            "available for scenarios whose Trace was exported"
        )
    try:
        explanation = reconstruct(
            entries, well, step, _schedule_from_step(index, step)
        )
    except LookupError as error:
        raise ToolFailure(
            f"no rule fired for well {well} at step {step}: there is no decision "
            f"to explain. {error}"
        ) from error
    rule = explanation.rule
    payload = {
        "rule": rule,
        "name": pick(RULE_NAMES, rule, context.lang),
        "statement": rule_statement(rule),
        "well": explanation.well,
        "step": explanation.control_step,
        "date": index.dates[explanation.control_step],
        "inputs": dict(explanation.inputs),
        "decision": explanation.decision,
        "why": explanation.why,
    }
    return Card(
        type="rule",
        title=title("rule", context.lang, rule=rule, well=well),
        payload=payload,
        provenance=index.provenance(),
    )


def _ablation_provenance(index: ScenarioIndex) -> str:
    meta = index.ablation.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("provenance")
        if isinstance(value, str):
            return value
    return "unknown"


def rule_impact(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    try:
        index = context.index()
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    rows = index.ablation.get("rules")
    if not rows:
        raise ToolFailure(
            f"scenario {index.scenario} carries no rule ablation: ablation.json "
            "is empty, so no rule contribution can be reported"
        )
    wanted = arguments.get("rule")
    measured: list[dict[str, Any]] = []
    for row in rows:
        rule = str(row["rule"])
        if wanted is not None and rule != str(wanted):
            continue
        measured.append(
            {
                "rule": rule,
                "name": pick(RULE_NAMES, rule, context.lang),
                "statement": rule_statement(rule),
                "delta": row.get("delta_npv"),
                "share": row.get("share"),
                "enabled": bool(row.get("enabled", True)),
                "measured": row.get("delta_npv") is not None,
                "disabled_reason": row.get("disabled_reason"),
            }
        )
    if not measured:
        raise ToolFailure(
            f"rule {wanted} is absent from the ablation of scenario "
            f"{index.scenario}: the ablation covers "
            f"{', '.join(str(row['rule']) for row in rows)}"
        )
    payload = {
        "npv_total": index.ablation.get("npv_total"),
        "rules": measured,
    }
    heading = (
        title("rule_one", context.lang, rule=wanted)
        if wanted is not None
        else title("rule_all", context.lang)
    )
    return Card(
        type="rule",
        title=heading,
        payload=payload,
        provenance=_ablation_provenance(index),
    )
