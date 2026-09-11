from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contexts.showcase.infrastructure.artifact_io import dump_bundle
from tests.support.backend.showcase_fixtures import make_synthetic_artifact
from backend.contexts.showcase.application.exporters.physics_view import (
    PHYSICS_INVARIANTS,
    PHYSICS_TOTAL,
    ScenarioPhysics,
    physics_json,
)
from backend.contexts.showcase.application.scenarios import (
    ScenarioRobustness,
    build_scenario_index,
    export_scenarios_json,
)

pytestmark = [pytest.mark.slow, pytest.mark.showcase]

ALL_SEVEN: tuple[str, ...] = PHYSICS_INVARIANTS

PARTIAL_REPORT: dict[str, object] = {
    "evaluated": [
        "NON_NEGATIVE",
        "WATERCUT_RANGE",
        "CUMULATIVE_MONOTONIC",
        "SHUT_WELL_FLOW",
        "BHP_LIMIT",
    ],
    "skipped": {
        "INJECTION_RESPONSE": "no reference forecast",
        "MATERIAL_BALANCE": "no reference forecast",
    },
    "counts": {"BHP_LIMIT": 3},
}


def _bundle(tmp_path: Path, scenario_id: str) -> Path:
    path = tmp_path / f"{scenario_id}.json"
    dump_bundle(make_synthetic_artifact(), path)
    return path


def test_seven_invariants_are_the_whole_set() -> None:
    assert PHYSICS_TOTAL == 7
    assert len(ALL_SEVEN) == 7


def test_partial_report_is_not_complete_and_lists_reasons() -> None:
    physics = ScenarioPhysics.from_dict(PARTIAL_REPORT)
    document = physics_json(physics)
    assert document is not None
    assert document["total"] == 7
    assert document["evaluated_count"] == 5
    assert document["complete"] is False
    assert document["admissible"] is False
    reasons = {item["invariant"]: item["reason"] for item in document["skipped"]}
    assert reasons == {
        "INJECTION_RESPONSE": "no reference forecast",
        "MATERIAL_BALANCE": "no reference forecast",
    }


def test_bhp_limit_counts_as_warning_not_blocking() -> None:
    physics = ScenarioPhysics.from_dict(PARTIAL_REPORT)
    document = physics_json(physics)
    assert document is not None
    assert document["blocking_count"] == 0
    assert document["warning_count"] == 3
    assert document["warning_invariants"] == ["BHP_LIMIT"]


def test_full_report_without_flags_is_admissible() -> None:
    physics = ScenarioPhysics.from_dict(
        {"evaluated": list(ALL_SEVEN), "skipped": {}, "counts": {}}
    )
    document = physics_json(physics)
    assert document is not None
    assert document["evaluated_count"] == 7
    assert document["complete"] is True
    assert document["admissible"] is True
    assert document["skipped"] == []


def test_full_report_with_blocking_flag_is_not_admissible() -> None:
    physics = ScenarioPhysics.from_dict(
        {"evaluated": list(ALL_SEVEN), "skipped": {}, "counts": {"NON_NEGATIVE": 2}}
    )
    assert physics.complete is True
    assert physics.blocking_count == 2
    assert physics.admissible is False


def test_full_report_with_only_bhp_flags_stays_admissible() -> None:
    physics = ScenarioPhysics.from_dict(
        {"evaluated": list(ALL_SEVEN), "skipped": {}, "counts": {"BHP_LIMIT": 9}}
    )
    assert physics.warning_count == 9
    assert physics.blocking_count == 0
    assert physics.admissible is True


def test_explicit_counts_from_report_are_trusted() -> None:
    physics = ScenarioPhysics.from_dict(
        {
            "evaluated": list(ALL_SEVEN),
            "skipped": {},
            "blocking_count": 4,
            "warning_count": 1,
        }
    )
    assert physics.blocking_count == 4
    assert physics.warning_count == 1


def test_unknown_invariant_is_rejected() -> None:
    with pytest.raises(ValueError):
        ScenarioPhysics(evaluated=("NOT_AN_INVARIANT",))


def test_invariant_cannot_be_evaluated_and_skipped_at_once() -> None:
    with pytest.raises(ValueError):
        ScenarioPhysics(
            evaluated=("BHP_LIMIT",), skipped=(("BHP_LIMIT", "no data"),)
        )


def test_skip_without_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        ScenarioPhysics(skipped=(("BHP_LIMIT", ""),))


def test_generator_writes_physics_block_when_data_exists(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "with-physics")
    index = build_scenario_index(
        [bundle],
        {
            "with-physics": ScenarioRobustness(
                physics=ScenarioPhysics.from_dict(PARTIAL_REPORT)
            )
        },
    )
    physics = index["scenarios"][0]["physics"]
    assert physics is not None
    assert physics["evaluated_count"] == 5
    assert physics["total"] == 7
    assert physics["complete"] is False
    assert [item["invariant"] for item in physics["skipped"]] == [
        "INJECTION_RESPONSE",
        "MATERIAL_BALANCE",
    ]


def test_generator_writes_null_when_physics_was_not_recorded(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "no-physics")
    index = build_scenario_index([bundle])
    entry = index["scenarios"][0]
    assert "physics" in entry
    assert entry["physics"] is None


def test_missing_physics_is_null_not_zero_and_not_empty_object(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path, "silent")
    out = tmp_path / "scenarios.json"
    export_scenarios_json([bundle], out)
    document = json.loads(out.read_text(encoding="utf-8"))
    physics = document["scenarios"][0]["physics"]
    assert physics is None
    assert physics != {}
    assert physics != 0


def test_exported_physics_survives_json_round_trip(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "roundtrip")
    out = tmp_path / "scenarios.json"
    export_scenarios_json(
        [bundle],
        out,
        {
            "roundtrip": ScenarioRobustness(
                physics=ScenarioPhysics.from_dict(PARTIAL_REPORT)
            )
        },
    )
    document = json.loads(out.read_text(encoding="utf-8"))
    physics = document["scenarios"][0]["physics"]
    assert physics["blocking_count"] == 0
    assert physics["warning_count"] == 3
    assert physics["warning_invariants"] == ["BHP_LIMIT"]
