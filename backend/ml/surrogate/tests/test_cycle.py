from __future__ import annotations

import json

import pytest

pytest.importorskip("torch")

from backend.ml.surrogate.cycle import CycleState, EXTRA_CONFIG, PILOT_CONFIG  # noqa: E402
from backend.ml.surrogate.dashboard import collect_status  # noqa: E402


def _size(config) -> int:
    return 1 + sum(
        (
            config.n_level_scenarios,
            config.n_unreachable_scenarios,
            config.n_shutdown_scenarios,
            config.n_conversion_scenarios,
        )
    )


def test_cycle_has_separate_exact_200_and_500_plans() -> None:
    assert _size(PILOT_CONFIG) == 200
    assert _size(EXTRA_CONFIG) == 500


def test_cycle_state_survives_reopen(tmp_path) -> None:
    first = CycleState(tmp_path)
    first.update_stage("pilot-200", completed=123)

    reopened = CycleState(tmp_path)

    assert reopened.stage("pilot-200")["completed"] == 123
    assert reopened.stage("extra-500")["status"] == "queued"


def test_new_phase_clears_stale_error(tmp_path) -> None:
    state = CycleState(tmp_path)
    state.payload["error"] = "old failure"
    state.save()

    state.phase("preparing_training_700")

    assert "error" not in state.payload


def test_dashboard_exposes_three_persistent_tabs(tmp_path) -> None:
    CycleState(tmp_path)
    pilot = tmp_path / "dataset-main"
    pilot.mkdir()
    (pilot / "plan.json").write_text(
        json.dumps({"plan_hash": "pilot", "scenarios": [{}] * 200}),
        encoding="utf-8",
    )
    (pilot / "manifest.jsonl").write_text(
        json.dumps(
            {
                "scenario_id": "baseline",
                "status": "OK",
                "family": "BASELINE",
                "wallclock_seconds": 10.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    status = collect_status(tmp_path)

    assert [stage["id"] for stage in status["stages"]] == [
        "pilot-200",
        "extra-500",
        "combined-700",
    ]
    assert status["stages"][0]["dataset"]["completed"] == 1
    assert status["stages"][1]["dataset"]["target"] == 500
    assert status["stages"][2]["dataset"]["target"] == 700


def test_dashboard_exposes_failed_training_details(tmp_path) -> None:
    state = CycleState(tmp_path)
    state.payload["phase"] = "failed"
    state.payload["error"] = "SurrogateModelError: bad target"
    state.update_stage("combined-700", status="training", max_epochs=80)

    status = collect_status(tmp_path)
    combined = status["stages"][2]

    assert combined["status"] == "failed"
    assert combined["training"]["failed"] is True
    assert combined["training"]["error"] == "SurrogateModelError: bad target"
    assert combined["training"]["max_epochs"] == 80
