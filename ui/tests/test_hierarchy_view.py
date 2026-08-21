from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from contracts import Groups, RunArtifact

from ui.fixtures import make_synthetic_artifact
from ui.hierarchy_view import (
    CONSTRAINTS,
    HEADROOM,
    build_hierarchy,
    export_hierarchy_json,
)

SEED = 20260815
TOLERANCE = 1e-6


def _regrouped(artifact: RunArtifact, groups: dict[str, tuple[str, ...]]) -> RunArtifact:
    return replace(
        artifact,
        groups=Groups(
            groups=groups,
            lambda_hash=artifact.groups.lambda_hash,
            group_hash=artifact.groups.group_hash,
        ),
    )


def test_one_entry_per_control_step() -> None:
    artifact = make_synthetic_artifact()
    hierarchy = build_hierarchy(artifact, SEED)
    steps = hierarchy["steps"]
    assert len(steps) == artifact.schedule.meta.n_control_dates
    assert [step["control_step"] for step in steps] == list(range(len(steps)))
    assert hierarchy["n_control_dates"] == artifact.schedule.meta.n_control_dates


def test_group_allocations_sum_to_what_the_group_received() -> None:
    hierarchy = build_hierarchy(make_synthetic_artifact(), SEED)
    for step in hierarchy["steps"]:
        for group in step["groups"]:
            total = sum(row["value_m3_per_day"] for row in group["allocations"])
            assert total == pytest.approx(
                group["received_m3_per_day"], abs=TOLERANCE
            )


def test_field_allocations_sum_to_the_field_limit() -> None:
    hierarchy = build_hierarchy(make_synthetic_artifact(), SEED)
    for step in hierarchy["steps"]:
        field = step["field"]
        total = sum(item["limit_m3_per_day"] for item in field["allocations"])
        assert total == pytest.approx(
            field["injection_limit_m3_per_day"], abs=TOLERANCE
        )
        assert field["water_available_m3_per_day"] == pytest.approx(
            field["injection_limit_m3_per_day"] * HEADROOM, abs=TOLERANCE
        )


def test_field_allocation_names_match_the_group_level() -> None:
    hierarchy = build_hierarchy(make_synthetic_artifact(), SEED)
    for step in hierarchy["steps"]:
        allocated = {item["group"]: item["limit_m3_per_day"] for item in step["field"]["allocations"]}
        received = {group["group"]: group["received_m3_per_day"] for group in step["groups"]}
        assert allocated == received


def test_groups_come_from_the_artifact_not_from_a_literal() -> None:
    artifact = _regrouped(
        make_synthetic_artifact(), {"NORTH": ("10", "11"), "SOUTH": ("12", "13")}
    )
    hierarchy = build_hierarchy(artifact, SEED)
    assert hierarchy["groups"] == ["NORTH", "SOUTH"]
    for step in hierarchy["steps"]:
        assert [group["group"] for group in step["groups"]] == ["NORTH", "SOUTH"]


def test_ungrouped_wells_are_listed_explicitly() -> None:
    artifact = _regrouped(make_synthetic_artifact(), {"G1": ("10", "11")})
    hierarchy = build_hierarchy(artifact, SEED)
    covered = {"10", "11"}
    expected = [
        well for well in artifact.schedule.meta.wells if well not in covered
    ]
    assert hierarchy["ungrouped"] == expected
    assert expected
    for step in hierarchy["steps"]:
        assert step["ungrouped"] == expected


def test_ungrouped_is_empty_list_when_the_slicing_covers_everything() -> None:
    hierarchy = build_hierarchy(make_synthetic_artifact(), SEED)
    assert hierarchy["ungrouped"] == []
    for step in hierarchy["steps"]:
        assert step["ungrouped"] == []


def test_well_rows_carry_rule_and_group_of_their_level() -> None:
    hierarchy = build_hierarchy(make_synthetic_artifact(), SEED)
    for step in hierarchy["steps"]:
        for row in step["wells"]:
            assert row["rule"] in ("R1", "R2")
            assert row["decision"].startswith(("SET_RATE", "SET_LRAT"))
            assert row["inputs"]
            assert row["constraint"] is None or row["constraint"] in CONSTRAINTS


def test_group_limit_in_well_inputs_matches_its_group() -> None:
    hierarchy = build_hierarchy(make_synthetic_artifact(), SEED)
    for step in hierarchy["steps"]:
        received = {group["group"]: group["received_m3_per_day"] for group in step["groups"]}
        for row in step["wells"]:
            if row["group"] is None:
                assert row["inputs"]["group_limit_m3_per_day"] is None
                continue
            assert row["inputs"]["group_limit_m3_per_day"] == received[row["group"]]


def test_both_branches_of_constraint_are_present() -> None:
    """`null` — ограничение не срабатывало, имя — сработало. Интерфейс рисует
    их по-разному, и обе ветки обязаны быть в данных, а не по везению."""

    hierarchy = build_hierarchy(make_synthetic_artifact(), SEED)
    seen = {
        row["constraint"] for step in hierarchy["steps"] for row in step["wells"]
    }
    assert None in seen
    assert seen - {None}
    assert seen - {None} <= set(CONSTRAINTS)


def test_not_commissioned_wells_leave_no_decision() -> None:
    artifact = make_synthetic_artifact()
    silent = artifact.schedule.meta.wells[-1]
    hierarchy = build_hierarchy(artifact, SEED)
    for step in hierarchy["steps"]:
        assert all(row["well"] != silent for row in step["wells"])


def test_generation_is_deterministic_for_one_seed() -> None:
    artifact = make_synthetic_artifact()
    assert build_hierarchy(artifact, SEED) == build_hierarchy(artifact, SEED)
    assert build_hierarchy(artifact, SEED) != build_hierarchy(artifact, SEED + 1)


def test_export_writes_compact_json(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    out = export_hierarchy_json(artifact, tmp_path / "hierarchy.json", SEED)
    text = out.read_text(encoding="utf-8")
    assert ", " not in text
    assert '": ' not in text
    data: dict[str, Any] = json.loads(text)
    assert data == build_hierarchy(artifact, SEED)


def test_no_deck_scale_literals_in_source() -> None:
    source = (Path(__file__).resolve().parents[1] / "hierarchy_view.py").read_text(
        encoding="utf-8"
    )
    for literal in ("225", "224", "103", "371"):
        assert literal not in source
