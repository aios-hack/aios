from __future__ import annotations

from typing import Any, Mapping

from backend.application.jarvis.artifacts import ArtifactError
from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure
from backend.application.jarvis.tools.labels import title

DEFAULT_LIMIT = 12


def connectivity(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    well = str(arguments["well"])
    limit = int(arguments.get("limit") or DEFAULT_LIMIT)
    min_weight = arguments.get("min_weight")
    try:
        index = context.index()
        index.require_well(well)
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    meta = index.graph.get("meta") or {}
    if not meta.get("lambda_measured", False):
        raise ToolFailure(
            f"connectivity was not measured in scenario {index.scenario}: the "
            "influence matrix is absent, so no graph neighbours can be named"
        )
    edges = index.edges_by_well.get(well)
    if not edges:
        raise ToolFailure(
            f"well {well} has no links in the measured influence matrix of "
            f"scenario {index.scenario}"
        )
    threshold = float(min_weight) if min_weight is not None else 0.0
    selected = [edge for edge in edges if float(edge["weight"]) >= threshold][:limit]
    if not selected:
        raise ToolFailure(
            f"well {well} has no links with weight at or above {threshold}: its "
            f"strongest neighbour weighs {float(edges[0]['weight'])}"
        )
    nodes = {str(node["id"]): node for node in index.graph.get("nodes", ())}
    highlight: list[str] = []
    rows: list[dict[str, Any]] = []
    for edge in selected:
        injector = str(edge["injector"])
        producer = str(edge["producer"])
        neighbour = producer if injector == well else injector
        if neighbour not in highlight:
            highlight.append(neighbour)
        rows.append(
            {
                "injector": injector,
                "producer": producer,
                "weight": float(edge["weight"]),
                "neighbour": neighbour,
            }
        )
    payload = {
        "focus": [well],
        "highlight": highlight,
        "edges": rows,
        "layer": "connectivity",
        "lag_months": meta.get("lag_months"),
        "window": index.graph.get("window"),
        "nodes": [
            {
                "id": identifier,
                "role": node.get("role"),
                "x": node.get("x"),
                "y": node.get("y"),
            }
            for identifier, node in nodes.items()
            if identifier == well or identifier in highlight
        ],
    }
    return Card(
        type="field-map",
        title=title("connectivity", context.lang, well=well),
        payload=payload,
        provenance=str(meta.get("provenance", "unknown")),
    )
