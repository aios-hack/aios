from __future__ import annotations

from typing import Any, Mapping

from backend.application.jarvis.artifacts import ArtifactError
from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure
from backend.application.jarvis.tools.labels import title

TOP_DIFF = 10


def _side(context: ToolContext, scenario: str) -> dict[str, Any]:
    try:
        entry = context.store.scenario_entry(scenario)
        index = context.index(scenario)
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    npv = entry.get("npv_methodology")
    if npv is None:
        npv = index.npv.get("npv_methodology")
    if npv is None:
        raise ToolFailure(
            f"scenario {scenario} has no NPV by the reference methodology: there "
            "is nothing to compare"
        )
    constraints = entry.get("constraints") or {}
    return {
        "id": scenario,
        "npv": float(npv),
        "status": {
            "converged": bool(entry.get("converged", False)),
            "self_consistent": bool(entry.get("self_consistent", False)),
            "is_submitted": bool(entry.get("is_submitted", False)),
            "ood_score": entry.get("ood_score"),
            "ood_threshold": entry.get("ood_threshold"),
        },
        "constraints": {
            key: constraints.get(key)
            for key in (
                "injection_limits",
                "liquid_limits",
                "production_floors",
                "watercut_limits",
                "well_outages",
                "infrastructure",
                "empty",
            )
        },
    }


def compare_scenarios(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    left = str(arguments["a"])
    right = str(arguments["b"])
    if left == right:
        raise ToolFailure(
            f"scenario {left} is being compared with itself: the difference is "
            "always zero, name two different scenarios"
        )
    a = _side(context, left)
    b = _side(context, right)
    index_a = context.index(left)
    index_b = context.index(right)
    diffs: list[dict[str, Any]] = []
    for well, row in index_a.npv_by_well.items():
        other = index_b.npv_by_well.get(well)
        if other is None:
            continue
        delta = float(other["with_allocated_tax"]) - float(row["with_allocated_tax"])
        diffs.append(
            {
                "well": well,
                "a": float(row["with_allocated_tax"]),
                "b": float(other["with_allocated_tax"]),
                "delta": delta,
            }
        )
    if not diffs:
        raise ToolFailure(
            f"scenarios {left} and {right} share no wells in the NPV breakdown: "
            "the per-well difference cannot be computed"
        )
    diffs.sort(key=lambda row: -abs(row["delta"]))
    payload = {
        "a": a,
        "b": b,
        "delta_npv": b["npv"] - a["npv"],
        "top_diff_wells": diffs[:TOP_DIFF],
    }
    return Card(
        type="compare",
        title=title("compare", context.lang, a=left, b=right),
        payload=payload,
        provenance=index_b.provenance(),
    )
