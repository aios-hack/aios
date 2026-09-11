from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.contexts.assistant.infrastructure.artifacts import ArtifactError, ScenarioIndex
from backend.contexts.assistant.application.tools.context import Card, ToolContext, ToolFailure
from backend.contexts.assistant.application.tools.labels import RULE_NAMES, pick

PROVENANCE = "policy"
NO_STEP = "no-council-step"
WELL_LIMIT = 12
LEVELS: tuple[str, ...] = ("FIELD", "GROUP", "WELL")
TITLES: Mapping[str, Mapping[str, str]] = {
    "council": {"ru": "Совет на шаге {step}", "en": "Council at step {step}"}
}


def _step_entry(index: ScenarioIndex, step: int) -> Mapping[str, Any]:
    direct = getattr(index.hierarchy, "step", None)
    if callable(direct):
        found = direct(step)
        if found is not None:
            return found
    steps = index.hierarchy.get("steps")
    if not isinstance(steps, Sequence) or not steps:
        raise ToolFailure(
            f"{NO_STEP}: в иерархии сценария {index.scenario} нет ни одного "
            "шага, поэтому решений совета не существует"
        )
    for entry in steps:
        if not isinstance(entry, Mapping):
            continue
        if int(entry.get("control_step", -1)) == step:
            return entry
    first = int(steps[0].get("control_step", 0))
    last = int(steps[-1].get("control_step", 0))
    raise ToolFailure(
        f"{NO_STEP}: шага {step} нет в иерархии сценария {index.scenario}: "
        f"журнал покрывает шаги с {first} по {last}"
    )


def _field_level(entry: Mapping[str, Any]) -> dict[str, Any]:
    field = entry.get("field") or {}
    allocations = field.get("allocations") or ()
    return {
        "rank": 0,
        "level": "FIELD",
        "agent": "FieldCoordinator",
        "verdict": "ALLOW",
        "bounds": [
            field.get("water_available_m3_per_day"),
            field.get("injection_limit_m3_per_day"),
        ],
        "decisions": [
            {
                "group": row.get("group"),
                "limit_m3_per_day": row.get("limit_m3_per_day"),
                "demand_rub_per_m3": row.get("demand_rub_per_m3"),
                "share_of_field": row.get("share_of_field"),
            }
            for row in allocations
        ],
        "allocated_m3_per_day": field.get("allocated_m3_per_day"),
    }


def _group_levels(entry: Mapping[str, Any], group: str | None) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for row in entry.get("groups") or ():
        name = str(row.get("group"))
        if group is not None and name != group:
            continue
        requested = row.get("requested_m3_per_day")
        received = row.get("received_m3_per_day")
        scaled = (
            isinstance(requested, (int, float))
            and isinstance(received, (int, float))
            and requested > received
        )
        collected.append(
            {
                "rank": 1,
                "level": "GROUP",
                "agent": "GroupAllocator",
                "group": name,
                "verdict": "VETO" if scaled else "ALLOW",
                "bounds": [requested, received],
                "decisions": [
                    {
                        "well": item.get("well"),
                        "value_m3_per_day": item.get("value_m3_per_day"),
                    }
                    for item in (row.get("allocations") or ())[:WELL_LIMIT]
                ],
                "trace_entries": row.get("trace_entries"),
            }
        )
    return collected


def _well_level(
    entry: Mapping[str, Any], lang: str, group: str | None, well: str | None
) -> dict[str, Any]:
    rows = entry.get("wells") or ()
    decisions: list[dict[str, Any]] = []
    for row in rows:
        if group is not None and str(row.get("group")) != group:
            continue
        if well is not None and str(row.get("well")) != well:
            continue
        rule = str(row.get("rule") or "")
        decisions.append(
            {
                "well": row.get("well"),
                "group": row.get("group"),
                "rule": rule,
                "rule_name": pick(RULE_NAMES, rule, lang) if rule else None,
                "decision": row.get("decision"),
                "constraint": row.get("constraint"),
                "inputs": dict(row.get("inputs") or {}),
            }
        )
    limited = decisions[:WELL_LIMIT]
    return {
        "rank": 2,
        "level": "WELL",
        "agent": "WellExecutor",
        "verdict": "ALLOW",
        "bounds": [],
        "decisions": limited,
        "total_decisions": len(decisions),
    }


def _outcome(levels: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    for level in levels:
        if level.get("level") != "WELL":
            continue
        decisions = level.get("decisions") or ()
        if decisions:
            head = decisions[0]
            return {
                "well": head.get("well"),
                "action": head.get("decision"),
                "rule": head.get("rule"),
                "constraint": head.get("constraint"),
            }
    return {"well": None, "action": None, "rule": None, "constraint": None}


def council_step(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    try:
        index = context.index()
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    requested = arguments.get("step")
    step = context.resolve_step(
        int(requested) if isinstance(requested, (int, float)) else None
    )
    group = arguments.get("group")
    group = str(group) if group is not None else None
    well = arguments.get("well")
    well = str(well) if well is not None else None
    entry = _step_entry(index, step)
    if group is not None:
        names = {str(row.get("group")) for row in entry.get("groups") or ()}
        if group not in names:
            listed = ", ".join(sorted(names)) or "ни одного"
            raise ToolFailure(
                f"участка {group!r} нет на шаге {step}: на этом шаге решения "
                f"принимались по участкам {listed}"
            )
    levels: list[dict[str, Any]] = [_field_level(entry)]
    levels.extend(_group_levels(entry, group))
    levels.append(_well_level(entry, context.lang, group, well))
    payload: dict[str, Any] = {
        "step": step,
        "date": index.dates[step] if step < len(index.dates) else None,
        "scenario": index.scenario,
        "group": group,
        "well": well,
        "agents_fired": list(entry.get("agents_fired") or ()),
        "decisions": entry.get("decisions"),
        "trace_entries_by_level": dict(entry.get("trace_entries_by_level") or {}),
        "levels": levels,
        "outcome": _outcome(levels),
        "source": "hierarchy.json",
    }
    title = TITLES["council"]
    return Card(
        type="council",
        title=title.get(context.lang, title["ru"]).format(step=step),
        payload=payload,
        provenance=_provenance(index),
    )


def _provenance(index: ScenarioIndex) -> str:
    meta = index.hierarchy.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("provenance")
        if isinstance(value, str):
            return value
    return PROVENANCE
