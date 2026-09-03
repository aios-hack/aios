from __future__ import annotations

from typing import Any, Mapping

from backend.application.jarvis.artifacts import ArtifactError
from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure
from backend.application.jarvis.tools.labels import (
    METRIC_LABELS,
    METRIC_UNITS,
    pick,
    title,
)

SPARK_WINDOW = 24
SERIES_METRICS: tuple[str, ...] = (
    "liquid_rate",
    "injection_rate",
    "watercut",
    "bhp",
)


def _spark(context: ToolContext, well: str, step: int) -> list[dict[str, Any]]:
    rows = context.index().require_well(well)
    start = max(0, step - SPARK_WINDOW + 1)
    points: list[dict[str, Any]] = []
    for value in range(start, step + 1):
        row = rows.steps.get(value)
        if row is None:
            continue
        points.append({"step": value, "value": row["liquid_rate"]})
    return points


def well_snapshot(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    well = str(arguments["well"])
    try:
        index = context.index()
        step = context.resolve_step(arguments.get("step"))
        rows = index.require_well(well)
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    row = rows.steps.get(step)
    if row is None:
        raise ToolFailure(
            f"well {well} has no row at step {step}: there is nothing to build a "
            "snapshot from"
        )
    npv_row = index.npv_by_well.get(well)
    payload: dict[str, Any] = {
        "well": well,
        "step": step,
        "date": index.dates[step],
        "role": row["role"],
        "availability": row["availability"],
        "operating_status": row["operating_status"],
        "liquid_rate": row["liquid_rate"],
        "injection_rate": row["injection_rate"],
        "watercut": row["watercut"],
        "bhp": row["bhp"],
        "setpoint": row["setpoint"],
        "npv": None if npv_row is None else npv_row["with_allocated_tax"],
        "spark": _spark(context, well, step),
    }
    return Card(
        type="well",
        title=title("well", context.lang, well=well),
        payload=payload,
        provenance=index.provenance(),
    )


def well_series(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    well = str(arguments["well"])
    metric = str(arguments["metric"])
    if metric not in SERIES_METRICS:
        raise ToolFailure(
            f"metric {metric} is not present in the showcase: available metrics "
            f"are {', '.join(SERIES_METRICS)}"
        )
    try:
        index = context.index()
        rows = index.require_well(well)
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
    series: list[dict[str, Any]] = []
    for step in range(from_step, to_step + 1):
        row = rows.steps.get(step)
        if row is None:
            continue
        series.append({"step": step, "date": index.dates[step], "value": row[metric]})
    if not series:
        raise ToolFailure(
            f"well {well} has no rows over the interval {from_step} to {to_step}: "
            "the series cannot be built"
        )
    label = pick(METRIC_LABELS, metric, context.lang)
    payload: dict[str, Any] = {
        "well": well,
        "metric": metric,
        "label": label,
        "unit": METRIC_UNITS[metric],
        "rows": series,
    }
    window = arguments.get("window")
    if isinstance(window, (list, tuple)) and len(window) == 2:
        payload["window"] = [int(window[0]), int(window[1])]
    return Card(
        type="series",
        title=title("series", context.lang, label=label.capitalize(), well=well),
        payload=payload,
        provenance=index.provenance(),
    )
