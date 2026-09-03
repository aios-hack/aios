from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.tools import run_tool
from backend.application.jarvis.tools.context import (
    ConsoleContext,
    ToolContext,
    ToolFailure,
)
from backend.application.jarvis.tools.fields import field_events_rows

STEP_2015 = 96
EVENTS_TOTAL = 36
EVENTS_2015 = [{"step": 102, "date": "2015-07-01", "well": "72", "type": "COMMISSIONED"}]


def make(store: ArtifactStore, **console: object) -> ToolContext:
    return ToolContext(store=store, console=ConsoleContext(**console))


def test_field_metrics_reads_real_step(store: ArtifactStore) -> None:
    card = run_tool("field_metrics", make(store, step=STEP_2015), {})
    assert card.type == "metric"
    values = {row["id"]: row["value"] for row in card.payload["metrics"]}
    assert values["active_wells"] == 96
    assert values["production"] == pytest.approx(40953.043091)
    assert values["compensation"] == pytest.approx(1.273941)
    assert values["npv_cumulative"] == pytest.approx(9116730554.167048)
    assert card.payload["date"] == "2015-01-01"


def test_field_metrics_carry_delta_and_spark(store: ArtifactStore) -> None:
    card = run_tool("field_metrics", make(store, step=STEP_2015), {})
    row = next(r for r in card.payload["metrics"] if r["id"] == "active_wells")
    assert row["delta"] is not None
    assert len(row["spark"]) == 24


def test_field_events_matches_frontend_rule(store: ArtifactStore) -> None:
    index = store.scenario("base")
    rows = field_events_rows(index)
    assert len(rows) == EVENTS_TOTAL
    kinds = {row["type"] for row in rows}
    assert kinds <= {"COMMISSIONED", "ROLE_CHANGE", "SHUT"}


def test_field_events_2015_window(store: ArtifactStore) -> None:
    card = run_tool(
        "field_events", make(store), {"from_step": 96, "to_step": 107}
    )
    assert card.type == "event-strip"
    trimmed = [
        {k: row[k] for k in ("step", "date", "well", "type")}
        for row in card.payload["events"]
    ]
    assert trimmed == EVENTS_2015


def test_field_events_filter_by_type(store: ArtifactStore) -> None:
    card = run_tool(
        "field_events", make(store), {"from_step": 0, "to_step": 224, "types": ["SHUT"]}
    )
    assert card.payload["events"] == []


def test_field_events_action_points_at_history(store: ArtifactStore) -> None:
    card = run_tool("field_events", make(store), {"from_step": 96, "to_step": 107})
    assert card.action["workspace"] == "history"
    assert card.action["view"] == "matrix"
    assert card.action["step"] == 102
    assert card.action["well"] == "72"


def test_field_events_rejects_interval_outside_horizon(store: ArtifactStore) -> None:
    with pytest.raises(ToolFailure):
        run_tool("field_events", make(store), {"from_step": 0, "to_step": 500})


def test_field_metrics_refuses_when_value_absent(
    tmp_path: Path, data_root: Path
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    shutil.copy(data_root / "scenarios.json", root / "scenarios.json")
    shutil.copy(data_root / "wells.json", root / "wells.json")
    for name in ("timeline", "npv", "graph", "hierarchy", "ablation", "trace"):
        shutil.copy(data_root / "base" / f"{name}.json", root / f"{name}.json")
    payload = json.loads((root / "timeline.json").read_text(encoding="utf-8"))
    payload["steps"][5]["field"]["compensation"] = None
    (root / "timeline.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    broken = ArtifactStore(root)
    with pytest.raises(ToolFailure) as error:
        run_tool("field_metrics", make(broken, step=5), {})
    assert "no zero is substituted" in str(error.value)
