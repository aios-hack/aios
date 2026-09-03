from __future__ import annotations

import pytest

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.tools import run_tool
from backend.application.jarvis.tools.registry import ToolInputError
from backend.application.jarvis.tools.context import (
    ConsoleContext,
    ToolContext,
    ToolFailure,
)

STEP_2015 = 96


def make(store: ArtifactStore, **console: object) -> ToolContext:
    return ToolContext(store=store, console=ConsoleContext(**console))


def test_well_snapshot_reads_real_row(store: ArtifactStore) -> None:
    context = make(store, step=STEP_2015)
    card = run_tool("well_snapshot", context, {"well": "13"})
    assert card.type == "well"
    assert card.payload["well"] == "13"
    assert card.payload["step"] == STEP_2015
    assert card.payload["date"] == "2015-01-01"
    assert card.payload["role"] in ("PROD", "INJ", "NONE")
    assert card.payload["npv"] == pytest.approx(-20491675.0, abs=1.0)
    assert len(card.payload["spark"]) == 24
    assert card.provenance == "model-z-base-run"


def test_well_snapshot_action_points_at_field(store: ArtifactStore) -> None:
    card = run_tool("well_snapshot", make(store, step=STEP_2015), {"well": "13"})
    assert card.action == {
        "scenario": "base",
        "workspace": "field",
        "view": "projection",
        "step": STEP_2015,
        "well": "13",
    }


def test_well_snapshot_unknown_well_fails_with_text(store: ArtifactStore) -> None:
    with pytest.raises(ToolFailure) as error:
        run_tool("well_snapshot", make(store, step=1), {"well": "45"})
    assert "well 45 is not in the stock" in str(error.value)


def test_watercut_null_stays_null(store: ArtifactStore) -> None:
    index = store.scenario("base")
    found = None
    for step in index.timeline["steps"]:
        for row in step["wells"]:
            if row["watercut"] is None:
                found = (int(step["control_step"]), str(row["well"]))
                break
        if found:
            break
    assert found is not None
    step, well = found
    card = run_tool("well_snapshot", make(store, step=step), {"well": well})
    assert card.payload["watercut"] is None


def test_well_series_window_and_unit(store: ArtifactStore) -> None:
    card = run_tool(
        "well_series",
        make(store),
        {"well": "13", "metric": "watercut", "from_step": 70, "to_step": 96},
    )
    assert card.type == "series"
    assert card.payload["unit"] == "fraction"
    assert len(card.payload["rows"]) == 27
    assert card.payload["rows"][0]["step"] == 70
    assert card.payload["rows"][-1]["date"] == "2015-01-01"


def test_well_series_rejects_interval_outside_horizon(store: ArtifactStore) -> None:
    with pytest.raises(ToolFailure) as error:
        run_tool(
            "well_series",
            make(store),
            {"well": "13", "metric": "bhp", "from_step": 0, "to_step": 900},
        )
    assert "does not fit the horizon" in str(error.value)


def test_well_series_rejects_unknown_metric(store: ArtifactStore) -> None:
    with pytest.raises(ToolInputError):
        run_tool("well_series", make(store), {"well": "13", "metric": "gor"})


def test_step_falls_back_to_context_date(store: ArtifactStore) -> None:
    card = run_tool(
        "well_snapshot", make(store, date="2015-01-01"), {"well": "13"}
    )
    assert card.payload["step"] == STEP_2015


def test_step_defaults_to_last_without_context(store: ArtifactStore) -> None:
    card = run_tool("well_snapshot", make(store), {"well": "13"})
    assert card.payload["step"] == 224
    assert card.payload["date"] == "2025-09-01"
