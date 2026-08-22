from __future__ import annotations

import json
from pathlib import Path

from backend.core.contracts import RunArtifact

from backend.presentation.ui_export.artifact_io import dump_bundle, load_bundle
from backend.presentation.ui_export.fixtures import SYNTHETIC_PROVENANCE, make_synthetic_artifact


def _dump_and_read(artifact: RunArtifact, path: Path) -> dict:
    dump_bundle(artifact, path)
    return json.loads(path.read_text(encoding="utf-8"))


def test_round_trip_identity(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    path = tmp_path / "bundle.json"
    dump_bundle(artifact, path)
    loaded = load_bundle(path)
    assert isinstance(loaded, RunArtifact)
    assert loaded == artifact


def test_bundle_contains_layers_window_and_flags(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    data = _dump_and_read(artifact, tmp_path / "bundle.json")
    assert data["schedule"]["fixed_deck_events"]
    assert data["schedule"]["control_events"]
    assert data["lambda_"]["window_start"] == "2007-01-01"
    assert data["lambda_"]["window_end"] == "2008-01-01"
    assert data["converged"] is True
    assert data["self_consistent"] is True


def test_axis_lengths_come_from_data(tmp_path: Path) -> None:
    sizes = ((3, 8, 5), (6, 20, 11))
    for n_wells, n_deck_dates, n_control_dates in sizes:
        artifact = make_synthetic_artifact(
            n_wells=n_wells,
            n_deck_dates=n_deck_dates,
            n_control_dates=n_control_dates,
        )
        path = tmp_path / f"bundle_{n_wells}_{n_deck_dates}_{n_control_dates}.json"
        dump_bundle(artifact, path)
        loaded = load_bundle(path)
        assert loaded == artifact
        assert len(loaded.schedule.meta.wells) == n_wells
        assert loaded.schedule.meta.n_control_dates == n_control_dates
        assert loaded.schedule.meta.n_intervals == n_control_dates - 1
        deck_axis = {s.deck_date_index for s in loaded.state_at_date}
        assert deck_axis == set(range(n_deck_dates))
        interval_axis = {r.control_step for r in loaded.interval_response}
        assert interval_axis == set(range(n_control_dates - 1))
        assert len(loaded.state_at_date) == n_deck_dates * n_wells
        assert len(loaded.interval_response) == (n_control_dates - 1) * n_wells
        assert set(loaded.npv_table.by_month) == set(range(n_control_dates - 1))


def test_synthetic_provenance_flag(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    path = tmp_path / "bundle.json"
    dump_bundle(artifact, path)
    loaded = load_bundle(path)
    assert loaded.schedule.meta.provenance == SYNTHETIC_PROVENANCE
    assert loaded.schedule.meta.provenance == "synthetic-fixture"


def test_final_npv_null_round_trip(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    path = tmp_path / "bundle.json"
    data = _dump_and_read(artifact, path)
    assert data["final_npv"] is None
    loaded = load_bundle(path)
    assert loaded.final_npv is None


def test_int_dict_keys_round_trip(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    path = tmp_path / "bundle.json"
    data = _dump_and_read(artifact, path)
    assert all(isinstance(k, str) for k in data["npv_table"]["by_year"])
    assert all(isinstance(k, str) for k in data["constraints"]["injection_limits"])
    loaded = load_bundle(path)
    assert all(isinstance(k, int) for k in loaded.npv_table.by_year)
    assert all(isinstance(k, int) for k in loaded.npv_table.by_month)
    assert all(isinstance(k, int) for k in loaded.constraints.injection_limits)
