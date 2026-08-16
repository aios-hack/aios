from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from contracts import Groups, Lambda, RunArtifact

LAYOUT_SEED: int = 20070101
LAYOUT_ITERATIONS: int = 220
LAYOUT_SIZE: float = 100.0
_SPRING_MIN: float = 8.0
_SPRING_MAX: float = 46.0
_REPULSION: float = 320.0
_ATTRACTION: float = 0.12
_MAX_STEP: float = 6.0
_EPS: float = 1e-9


def _rng_unit(state: int) -> tuple[float, int]:
    nxt = (state * 6364136223846793005 + 1442695040888963407) % (1 << 64)
    return (nxt >> 11) / float(1 << 53), nxt


def _edges(lambda_: Lambda) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for row, producer in enumerate(lambda_.producers):
        for col, injector in enumerate(lambda_.injectors):
            weight = lambda_.matrix[row][col]
            if weight == 0.0:
                continue
            edges.append(
                {"injector": injector, "producer": producer, "weight": weight}
            )
    return edges


def _group_of(groups: Groups) -> dict[str, str]:
    membership: dict[str, str] = {}
    for group_id in sorted(groups.groups):
        for well in groups.groups[group_id]:
            membership.setdefault(well, group_id)
    return membership


def _spring_lengths(
    edges: list[dict[str, Any]],
) -> dict[tuple[str, str], float]:
    weights = [abs(edge["weight"]) for edge in edges]
    if not weights:
        return {}
    low = min(weights)
    high = max(weights)
    span = high - low
    lengths: dict[tuple[str, str], float] = {}
    for edge in edges:
        share = 0.0 if span <= _EPS else (abs(edge["weight"]) - low) / span
        lengths[(edge["injector"], edge["producer"])] = _SPRING_MAX - share * (
            _SPRING_MAX - _SPRING_MIN
        )
    return lengths


def _initial_positions(nodes: list[str]) -> dict[str, list[float]]:
    positions: dict[str, list[float]] = {}
    state = LAYOUT_SEED
    radius = LAYOUT_SIZE / 2.0
    for index, node in enumerate(nodes):
        jitter, state = _rng_unit(state)
        angle = 2.0 * math.pi * index / max(1, len(nodes))
        span = radius * (0.35 + 0.5 * jitter)
        positions[node] = [
            radius + span * math.cos(angle),
            radius + span * math.sin(angle),
        ]
    return positions


def _layout(
    nodes: list[str], edges: list[dict[str, Any]]
) -> dict[str, dict[str, float]]:
    positions = _initial_positions(nodes)
    lengths = _spring_lengths(edges)
    temperature = LAYOUT_SIZE / 8.0
    cooling = temperature / (LAYOUT_ITERATIONS + 1)
    for _ in range(LAYOUT_ITERATIONS):
        forces = {node: [0.0, 0.0] for node in nodes}
        for i, first in enumerate(nodes):
            for second in nodes[i + 1 :]:
                dx = positions[first][0] - positions[second][0]
                dy = positions[first][1] - positions[second][1]
                distance = math.hypot(dx, dy)
                if distance < _EPS:
                    dx, dy, distance = 0.01, 0.01, 0.0141
                push = _REPULSION / (distance * distance)
                ux, uy = dx / distance, dy / distance
                forces[first][0] += ux * push
                forces[first][1] += uy * push
                forces[second][0] -= ux * push
                forces[second][1] -= uy * push
        for edge in edges:
            source = edge["injector"]
            target = edge["producer"]
            rest = lengths[(source, target)]
            dx = positions[target][0] - positions[source][0]
            dy = positions[target][1] - positions[source][1]
            distance = math.hypot(dx, dy)
            if distance < _EPS:
                continue
            pull = _ATTRACTION * (distance - rest)
            ux, uy = dx / distance, dy / distance
            forces[source][0] += ux * pull
            forces[source][1] += uy * pull
            forces[target][0] -= ux * pull
            forces[target][1] -= uy * pull
        for node in nodes:
            fx, fy = forces[node]
            magnitude = math.hypot(fx, fy)
            if magnitude < _EPS:
                continue
            step = min(magnitude, temperature, _MAX_STEP)
            positions[node][0] += fx / magnitude * step
            positions[node][1] += fy / magnitude * step
        temperature -= cooling
    return _normalize(nodes, positions)


def _normalize(
    nodes: list[str], positions: dict[str, list[float]]
) -> dict[str, dict[str, float]]:
    xs = [positions[node][0] for node in nodes]
    ys = [positions[node][1] for node in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    scale = LAYOUT_SIZE / max(max_x - min_x, max_y - min_y, _EPS)
    return {
        node: {
            "x": round((positions[node][0] - min_x) * scale, 4),
            "y": round((positions[node][1] - min_y) * scale, 4),
        }
        for node in nodes
    }


def build_lambda_graph(artifact: RunArtifact) -> dict[str, Any]:
    lambda_ = artifact.lambda_
    edges = _edges(lambda_)
    membership = _group_of(artifact.groups)
    injectors = list(lambda_.injectors)
    producers = list(lambda_.producers)
    node_ids = injectors + [well for well in producers if well not in injectors]
    coordinates = _layout(node_ids, edges)
    nodes = [
        {
            "id": well,
            "role": "INJ" if well in set(injectors) else "PROD",
            "group": membership.get(well),
            "x": coordinates[well]["x"],
            "y": coordinates[well]["y"],
        }
        for well in node_ids
    ]
    weights = [abs(edge["weight"]) for edge in edges]
    return {
        "window": {
            "start": lambda_.window_start.isoformat(),
            "end": lambda_.window_end.isoformat(),
        },
        "nodes": nodes,
        "edges": edges,
        "groups": [
            {"id": group_id, "wells": list(artifact.groups.groups[group_id])}
            for group_id in sorted(artifact.groups.groups)
        ],
        "weight_range": {
            "min": min(weights) if weights else 0.0,
            "max": max(weights) if weights else 0.0,
        },
        "meta": {
            "lag_months": lambda_.lag_months,
            "amplitude": lambda_.amplitude,
            "stability": lambda_.stability,
            "rank": lambda_.rank,
            "condition_number": lambda_.condition_number,
        },
        "layout": {"size": LAYOUT_SIZE, "seed": LAYOUT_SEED},
    }


def export_graph_json(artifact: RunArtifact, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_lambda_graph(artifact), ensure_ascii=False, indent=2, sort_keys=True
        ),
        encoding="utf-8",
    )
    return out
