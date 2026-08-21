from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import date
from pathlib import Path

from aios_backend.core.contracts import Groups, Lambda, RunArtifact
from aios_backend.presentation.ui_export.fixtures import make_synthetic_artifact
from aios_backend.presentation.ui_export.graph_view import build_lambda_graph, export_graph_json

_PLACEHOLDER_HASH = "0" * 64


def _contrasted_artifact() -> RunArtifact:
    artifact = make_synthetic_artifact(n_wells=6)
    producers = ("P1", "P2", "P3")
    injectors = ("I1", "I2")
    lambda_ = Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2008, 7, 1),
        producers=producers,
        injectors=injectors,
        matrix=(
            (0.9, 0.0),
            (0.85, 0.0),
            (0.0, 0.8),
        ),
        lag_months=3,
        amplitude=0.2,
        stability=0.77,
        rank=2,
        condition_number=4.25,
        achievability_ok={"I1": True, "I2": False},
    )
    groups = Groups(
        groups={"G1": ("I1", "P1", "P2"), "G2": ("I2", "P3")},
        lambda_hash=_PLACEHOLDER_HASH,
        group_hash=_PLACEHOLDER_HASH,
    )
    return replace(artifact, lambda_=lambda_, groups=groups)


def _distance(graph: dict, first: str, second: str) -> float:
    nodes = {node["id"]: node for node in graph["nodes"]}
    return math.hypot(
        nodes[first]["x"] - nodes[second]["x"],
        nodes[first]["y"] - nodes[second]["y"],
    )


def test_nodes_cover_producers_and_injectors() -> None:
    artifact = _contrasted_artifact()
    graph = build_lambda_graph(artifact)
    ids = {node["id"] for node in graph["nodes"]}
    assert ids == set(artifact.lambda_.producers) | set(artifact.lambda_.injectors)
    roles = {node["id"]: node["role"] for node in graph["nodes"]}
    assert roles["I1"] == "INJ"
    assert roles["P1"] == "PROD"


def test_edges_only_for_nonzero_lambda_with_matrix_weight() -> None:
    artifact = _contrasted_artifact()
    graph = build_lambda_graph(artifact)
    pairs = {(edge["injector"], edge["producer"]): edge["weight"] for edge in graph["edges"]}
    assert pairs == {
        ("I1", "P1"): 0.9,
        ("I1", "P2"): 0.85,
        ("I2", "P3"): 0.8,
    }
    assert ("I2", "P1") not in pairs
    assert all(edge["weight"] != 0.0 for edge in graph["edges"])


def test_window_is_present_in_output() -> None:
    graph = build_lambda_graph(_contrasted_artifact())
    assert graph["window"] == {"start": "2007-01-01", "end": "2008-07-01"}


def test_groups_cover_every_node() -> None:
    graph = build_lambda_graph(_contrasted_artifact())
    assert all(node["group"] is not None for node in graph["nodes"])
    grouped = {well for group in graph["groups"] for well in group["wells"]}
    assert {node["id"] for node in graph["nodes"]} <= grouped


def test_metadata_carries_lambda_diagnostics() -> None:
    graph = build_lambda_graph(_contrasted_artifact())
    assert graph["meta"]["lag_months"] == 3
    assert graph["meta"]["amplitude"] == 0.2
    assert graph["meta"]["stability"] == 0.77


def test_layout_is_deterministic() -> None:
    artifact = _contrasted_artifact()
    first = build_lambda_graph(artifact)
    second = build_lambda_graph(artifact)
    assert [(n["id"], n["x"], n["y"]) for n in first["nodes"]] == [
        (n["id"], n["x"], n["y"]) for n in second["nodes"]
    ]


def test_strongly_linked_nodes_are_closer_than_unlinked() -> None:
    graph = build_lambda_graph(_contrasted_artifact())
    linked = _distance(graph, "I1", "P1")
    unlinked = _distance(graph, "I1", "P3")
    assert linked < unlinked


def test_export_writes_readable_json(tmp_path: Path) -> None:
    out = export_graph_json(_contrasted_artifact(), tmp_path / "graph.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["window"]["start"] == "2007-01-01"
    assert len(data["nodes"]) == 5
    assert len(data["edges"]) == 3
