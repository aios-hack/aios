from __future__ import annotations

from typing import Any, Mapping

from backend.application.jarvis.artifacts import ArtifactError, ScenarioIndex
from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure
from backend.application.jarvis.tools.labels import (
    EVENT_LABELS,
    METRIC_LABELS,
    METRIC_UNITS,
    pick,
    title,
)

FIELD_KEYS: tuple[str, ...] = (
    "active_wells",
    "production",
    "injection",
    "compensation",
    "npv_cumulative",
)
SPARK_WINDOW = 24


def _event_type(previous: Mapping[str, Any], current: Mapping[str, Any]) -> str | None:
    if previous["availability"] != "AVAILABLE" and current["availability"] == "AVAILABLE":
        return "COMMISSIONED"
    if previous["role"] != current["role"] and current["role"] == "INJ":
        return "ROLE_CHANGE"
    if previous["operating_status"] != "SHUT" and current["operating_status"] == "SHUT":
        return "SHUT"
    return None


def field_events_rows(index: ScenarioIndex, lang: str = "ru") -> list[dict[str, Any]]:
    steps = index.timeline["steps"]
    events: list[dict[str, Any]] = []
    for position in range(1, len(steps)):
        previous = {row["well"]: row for row in steps[position - 1]["wells"]}
        for current in steps[position]["wells"]:
            before = previous.get(current["well"])
            if before is None:
                continue
            kind = _event_type(before, current)
            if kind is None:
                continue
            events.append(
                {
                    "step": position,
                    "date": index.dates[position],
                    "well": str(current["well"]),
                    "type": kind,
                    "label": pick(EVENT_LABELS, kind, lang),
                }
            )
    return events


def _spark(index: ScenarioIndex, key: str, step: int) -> list[dict[str, Any]]:
    steps = index.timeline["steps"]
    start = max(0, step - SPARK_WINDOW + 1)
    points: list[dict[str, Any]] = []
    for position in range(start, step + 1):
        value = steps[position]["field"].get(key)
        if value is None:
            continue
        points.append({"step": position, "value": value})
    return points


def field_metrics(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    try:
        index = context.index()
        step = context.resolve_step(arguments.get("step"))
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    row = index.timeline["steps"][step]["field"]
    previous = index.timeline["steps"][step - 1]["field"] if step > 0 else None
    metrics: list[dict[str, Any]] = []
    for key in FIELD_KEYS:
        value = row.get(key)
        if value is None:
            raise ToolFailure(
                f"field value {key} is absent at step {step} in scenario "
                f"{index.scenario}: the field summary cannot be assembled and no "
                "zero is substituted for a missing measurement"
            )
        delta = None
        if previous is not None and previous.get(key) is not None:
            delta = value - previous[key]
        metrics.append(
            {
                "id": key,
                "label": pick(METRIC_LABELS, key, context.lang),
                "value": value,
                "unit": METRIC_UNITS[key],
                "delta": delta,
                "spark": _spark(index, key, step),
            }
        )
    return Card(
        type="metric",
        title=title("field", context.lang, date=index.dates[step]),
        payload={"step": step, "date": index.dates[step], "metrics": metrics},
        provenance=index.provenance(),
    )


def field_events(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    try:
        index = context.index()
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    last = index.step_count() - 1
    from_step = int(arguments.get("from_step") or 0)
    to_step = int(arguments["to_step"]) if arguments.get("to_step") is not None else last
    if from_step < 0 or to_step > last or from_step > to_step:
        raise ToolFailure(
            f"the step interval {from_step} to {to_step} does not fit the horizon "
            f"of scenario {index.scenario}: the available steps are 0 to {last}"
        )
    wanted = arguments.get("types")
    selected = set(wanted) if wanted else None
    rows = [
        event
        for event in field_events_rows(index, context.lang)
        if from_step <= event["step"] <= to_step
        and (selected is None or event["type"] in selected)
    ]
    payload = {
        "from_step": from_step,
        "to_step": to_step,
        "from_date": index.dates[from_step],
        "to_date": index.dates[to_step],
        "events": rows,
    }
    return Card(
        type="event-strip",
        title=title(
            "events",
            context.lang,
            a=index.dates[from_step],
            b=index.dates[to_step],
        ),
        payload=payload,
        provenance=index.provenance(),
    )
