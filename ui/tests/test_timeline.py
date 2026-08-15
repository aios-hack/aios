from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from contracts import ControlEvent, EventKind, RunArtifact

from ui.fixtures import make_synthetic_artifact
from ui.timeline import build_timeline, export_timeline_json

DENSITIES = {"10": 900.0, "11": 910.0, "12": 920.0, "13": 930.0, "14": 940.0}


def _well_entry(step: dict[str, Any], well: str) -> dict[str, Any]:
    return next(row for row in step["wells"] if row["well"] == well)


def _with_events(artifact: RunArtifact, *events: ControlEvent) -> RunArtifact:
    schedule = replace(
        artifact.schedule,
        control_events=tuple(artifact.schedule.control_events) + events,
    )
    return replace(artifact, schedule=schedule)


def test_frame_count_and_terminal_nulls() -> None:
    artifact = make_synthetic_artifact()
    timeline = build_timeline(artifact, DENSITIES)
    steps = timeline["steps"]
    assert len(steps) == artifact.schedule.meta.n_control_dates
    assert all(not step["terminal"] for step in steps[:-1])
    last = steps[-1]
    assert last["terminal"] is True
    assert last["field"]["production"] is None
    assert last["field"]["injection"] is None
    assert last["field"]["compensation"] is None
    assert all(row["watercut"] is None for row in last["wells"])
    assert steps[0]["field"]["production"] is not None


def test_fold_shut_and_convert_inj() -> None:
    artifact = _with_events(
        make_synthetic_artifact(),
        ControlEvent(control_step=2, well="11", kind=EventKind.SHUT),
        ControlEvent(control_step=4, well="13", kind=EventKind.CONVERT_INJ),
    )
    steps = build_timeline(artifact, DENSITIES)["steps"]
    assert _well_entry(steps[1], "11")["operating_status"] == "OPEN"
    assert _well_entry(steps[2], "11")["operating_status"] == "SHUT"
    assert _well_entry(steps[3], "11")["operating_status"] == "OPEN"
    assert _well_entry(steps[3], "13")["role"] == "PROD"
    assert _well_entry(steps[4], "13")["role"] == "INJ"
    assert _well_entry(steps[4], "13")["setpoint"] == 0.0


def test_join_has_no_off_by_one() -> None:
    artifact = make_synthetic_artifact()
    meta = artifact.schedule.meta
    n_deck_dates = len({row.deck_date_index for row in artifact.state_at_date})
    offset = n_deck_dates - meta.n_control_dates
    state_rows = {
        (row.deck_date_index, row.well): row for row in artifact.state_at_date
    }
    steps = build_timeline(artifact, DENSITIES)["steps"]
    for k in (0, meta.n_intervals // 2, meta.n_intervals - 1):
        for well in ("10", "12"):
            entry = _well_entry(steps[k], well)
            row = state_rows[(offset + 1 + k, well)]
            assert entry["liquid_rate"] == row.liquid_rate
            assert entry["injection_rate"] == row.injection_rate
            assert entry["bhp"] == row.bhp
    terminal = steps[meta.n_control_dates - 1]
    row = state_rows[(n_deck_dates - 1, "12")]
    assert _well_entry(terminal, "12")["liquid_rate"] == row.liquid_rate
    assert _well_entry(terminal, "12")["bhp"] == row.bhp


def test_npv_accumulates_by_month() -> None:
    artifact = make_synthetic_artifact()
    by_month = artifact.npv_table.by_month
    steps = build_timeline(artifact, DENSITIES)["steps"]
    previous = float("-inf")
    for k, step in enumerate(steps):
        expected = sum(
            by_month[j].discounted_fcf for j in range(min(k, len(by_month) - 1) + 1)
        )
        assert step["field"]["npv_cumulative"] == pytest.approx(expected)
        assert step["field"]["npv_cumulative"] > previous or k == len(steps) - 1
        previous = step["field"]["npv_cumulative"]
    assert steps[-1]["field"]["npv_cumulative"] == pytest.approx(
        sum(item.discounted_fcf for item in by_month.values())
    )


def test_watercut_uses_given_densities() -> None:
    artifact = make_synthetic_artifact()
    responses = {
        (row.control_step, row.well): row for row in artifact.interval_response
    }
    steps = build_timeline(artifact, DENSITIES)["steps"]
    for k in (0, 2, 5):
        response = responses[(k, "11")]
        expected = 1.0 - (
            response.oil_mass_delta / (DENSITIES["11"] / 1000.0)
        ) / response.liquid_volume_delta
        assert _well_entry(steps[k], "11")["watercut"] == pytest.approx(expected)
        assert _well_entry(steps[k], "10")["watercut"] == 0.0
        assert _well_entry(steps[k], "14")["watercut"] == 0.0


def test_missing_density_raises_key_error() -> None:
    artifact = make_synthetic_artifact()
    with pytest.raises(KeyError):
        build_timeline(artifact, {})


def test_field_aggregates_sum_interval_response() -> None:
    artifact = make_synthetic_artifact()
    steps = build_timeline(artifact, DENSITIES)["steps"]
    k = 1
    rows = [row for row in artifact.interval_response if row.control_step == k]
    production = sum(row.liquid_volume_delta for row in rows)
    injection = sum(row.injection_volume_delta for row in rows)
    field = steps[k]["field"]
    assert field["production"] == pytest.approx(production)
    assert field["injection"] == pytest.approx(injection)
    assert field["compensation"] == pytest.approx(injection / production)
    assert field["active_wells"] == 4


def test_export_writes_dates_and_frames(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    out = export_timeline_json(artifact, DENSITIES, tmp_path / "timeline.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["steps"]) == data["n_control_dates"]
    assert data["steps"][0]["date"] == "2007-01-01"
    assert data["steps"][1]["date"] == "2007-02-01"
    assert data["steps"][-1]["date"] == "2007-07-01"


def test_no_deck_scale_literals_in_source() -> None:
    source = (Path(__file__).resolve().parents[1] / "timeline.py").read_text(
        encoding="utf-8"
    )
    for literal in ("146", "147", "225", "103"):
        assert literal not in source
