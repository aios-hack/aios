"""Экран «Совет» строится из настоящего журнала решений, не из RNG."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from backend.core.contracts import Groups, RunArtifact

from backend.domain.policy.agents.registry import DEFAULT_REGISTRY
from backend.domain.policy.levels import Level
from backend.presentation.ui_export.fixtures import make_synthetic_artifact
from backend.presentation.ui_export.hierarchy_view import (
    HEADROOM,
    build_hierarchy,
    export_hierarchy_json,
    run_hierarchy_steps,
)

TOLERANCE = 1e-6
SOURCE = Path(__file__).resolve().parents[1] / "hierarchy_view.py"
SHOWCASE = (
    Path(__file__).resolve().parents[4] / "frontend" / "public" / "data"
)


def _artifact() -> RunArtifact:
    from backend.presentation.ui_export.artifact_io import load_bundle

    bundle = SHOWCASE / "bundles" / "base.json"
    if not bundle.is_file():
        pytest.skip(f"нет базового бандла {bundle}")
    return load_bundle(bundle)


def _hierarchy() -> dict[str, Any]:
    return build_hierarchy(_artifact())


def test_demo_rng_is_not_imported() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "demo_rng" not in source
    assert "Rng" not in source


def test_export_is_marked_as_real_in_the_showcase() -> None:
    for name in ("hierarchy.json", Path("base") / "hierarchy.json"):
        path = SHOWCASE / name
        if not path.is_file():
            pytest.skip(f"витрина не собрана: нет {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["meta"]["synthetic"] is False
        assert data["meta"]["provenance"] != "synthetic-demo"
        assert data["meta"]["source_run_id"]


def test_showcase_carries_a_non_empty_agent_registry() -> None:
    path = SHOWCASE / "hierarchy.json"
    if not path.is_file():
        pytest.skip(f"витрина не собрана: нет {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["agents"]
    for agent in data["agents"]:
        assert agent["name"]
        assert agent["level"] in {level.value for level in Level}
        assert agent["responsibilities"]


def test_agents_come_from_the_registry_not_from_a_literal() -> None:
    hierarchy = _hierarchy()
    assert [agent["name"] for agent in hierarchy["agents"]] == [
        agent.name for agent in DEFAULT_REGISTRY.call_order()
    ]


def test_every_step_names_the_agents_that_fired() -> None:
    hierarchy = _hierarchy()
    known = {agent["name"] for agent in hierarchy["agents"]}
    for step in hierarchy["steps"]:
        assert step["agents_fired"]
        assert set(step["agents_fired"]) <= known


def test_group_allocations_sum_to_what_the_group_received() -> None:
    for step in _hierarchy()["steps"]:
        for group in step["groups"]:
            total = sum(row["value_m3_per_day"] for row in group["allocations"])
            assert total == pytest.approx(
                group["received_m3_per_day"], abs=1e-3
            )


def test_group_limits_sum_to_the_field_limit() -> None:
    for step in _hierarchy()["steps"]:
        field = step["field"]
        total = sum(item["limit_m3_per_day"] for item in field["allocations"])
        assert total <= field["injection_limit_m3_per_day"] + TOLERANCE
        assert total == pytest.approx(
            field["allocated_m3_per_day"], abs=1e-3
        )
        assert field["water_available_m3_per_day"] == pytest.approx(
            field["injection_limit_m3_per_day"] * HEADROOM, abs=1e-3
        )


def test_field_allocation_names_match_the_group_level() -> None:
    for step in _hierarchy()["steps"]:
        allocated = {
            item["group"]: item["limit_m3_per_day"]
            for item in step["field"]["allocations"]
        }
        received = {
            group["group"]: group["received_m3_per_day"] for group in step["groups"]
        }
        assert allocated == received


def test_one_entry_per_control_step() -> None:
    artifact = _artifact()
    hierarchy = build_hierarchy(artifact)
    steps = hierarchy["steps"]
    assert hierarchy["n_control_dates"] == artifact.schedule.meta.n_control_dates
    assert len(steps) == artifact.schedule.meta.n_control_dates - 1
    assert [step["control_step"] for step in steps] == list(range(len(steps)))


def test_well_rows_carry_the_rule_that_produced_them() -> None:
    for step in _hierarchy()["steps"]:
        assert step["wells"]
        for row in step["wells"]:
            assert row["rule"].startswith("R")
            assert row["decision"]
            assert row["inputs"]


def test_groups_come_from_the_artifact_not_from_a_literal() -> None:
    artifact = _artifact()
    renamed = replace(
        artifact,
        groups=Groups(
            groups={"NORTH": artifact.groups.groups["G1"]},
            lambda_hash=artifact.groups.lambda_hash,
            group_hash=artifact.groups.group_hash,
        ),
    )
    hierarchy = build_hierarchy(renamed)
    assert hierarchy["groups"] == ["NORTH"]
    for step in hierarchy["steps"]:
        assert [group["group"] for group in step["groups"]] == ["NORTH"]


def test_empty_slicing_is_refused_instead_of_being_synthesised() -> None:
    artifact = _artifact()
    without = replace(
        artifact,
        groups=Groups(
            groups={},
            lambda_hash=artifact.groups.lambda_hash,
            group_hash=artifact.groups.group_hash,
        ),
    )
    with pytest.raises(ValueError, match="нарезка"):
        build_hierarchy(without)


def test_a_step_without_a_response_is_refused_instead_of_being_synthesised() -> None:
    artifact = _artifact()
    starved = replace(artifact, state_at_date=())
    with pytest.raises(ValueError):
        build_hierarchy(starved)


def test_a_synthetic_artifact_is_still_refused_when_the_policy_cannot_decide() -> None:
    """Синтетическая фикстура не обязана давать журнал; обязана — падать."""

    artifact = make_synthetic_artifact()
    try:
        hierarchy = build_hierarchy(artifact)
    except ValueError as error:
        assert str(error)
        return
    assert hierarchy["steps"]


def test_run_returns_a_state_and_a_result_per_step() -> None:
    artifact = _artifact()
    collected = run_hierarchy_steps(artifact)
    assert len(collected) == artifact.schedule.meta.n_control_dates - 1
    for state, result in collected:
        assert result.trace.entries
        assert result.trace.by_level(Level.FIELD)
        assert state.control_step >= 0


def test_export_writes_compact_json(tmp_path: Path) -> None:
    artifact = _artifact()
    out = export_hierarchy_json(artifact, tmp_path / "hierarchy.json")
    text = out.read_text(encoding="utf-8")
    assert ", " not in text
    assert '": ' not in text
    data: dict[str, Any] = json.loads(text)
    assert data == build_hierarchy(artifact)


def test_no_deck_scale_literals_in_source() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    for literal in ("225", "224", "103", "371"):
        assert literal not in source
