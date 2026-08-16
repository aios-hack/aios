from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import N_CONTROL_DATES
from ui.artifact_io import load_bundle
from ui.deck import load_wellheads
from ui.demo import BASE_ID, WHATIF_ID, build_demo, deck_scale, demo_meta
from ui.demo_artifact import DEMO_PROVENANCE
from ui.graph_view import build_lambda_graph
from ui.npv_view import build_npv_by_well
from ui.scenarios import build_scenario_index
from ui.timeline import build_timeline
from ui.webdata import DEFAULT_DECK_PATH

VIEW_FILES = ("timeline.json", "graph.json", "npv.json", "trace.json")


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("demo")
    build_demo(out)
    return out


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_scale_comes_from_the_deck_not_from_literals(demo_dir: Path) -> None:
    expected_wells = len(load_wellheads(DEFAULT_DECK_PATH))
    timeline = _read(demo_dir / "timeline.json")
    assert len(timeline["wells"]) == expected_wells
    assert len(timeline["steps"]) == N_CONTROL_DATES
    assert timeline["n_intervals"] == N_CONTROL_DATES - 1
    assert len(_read(demo_dir / "npv.json")["wells"]) == expected_wells
    assert len(_read(demo_dir / "wells.json")["wells"]) == expected_wells


def test_generation_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    build_demo(first)
    build_demo(second)
    for path in sorted(first.rglob("*.json")):
        twin = second / path.relative_to(first)
        assert twin.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_every_exported_file_carries_the_synthetic_flag(demo_dir: Path) -> None:
    for scenario in ("", BASE_ID, WHATIF_ID):
        for name in VIEW_FILES:
            data = _read(demo_dir / scenario / name if scenario else demo_dir / name)
            meta = data["__meta__"] if name == "trace.json" else data["meta"]
            assert meta["provenance"] == DEMO_PROVENANCE
            assert meta["synthetic"] is True
            assert meta["notice_ru"] and meta["notice_en"]
    assert _read(demo_dir / "scenarios.json")["meta"]["provenance"] == DEMO_PROVENANCE


def test_wells_json_is_marked_as_real_deck_geometry(demo_dir: Path) -> None:
    meta = _read(demo_dir / "wells.json")["meta"]
    assert meta["provenance"] == "deck"
    assert meta["synthetic"] is False


def test_bundles_validate_against_the_artifact_loader(demo_dir: Path) -> None:
    for name in (BASE_ID, WHATIF_ID):
        artifact = load_bundle(demo_dir / "bundles" / f"{name}.json")
        assert artifact.schedule.meta.provenance == DEMO_PROVENANCE
        assert len(artifact.schedule.meta.wells) == len(deck_scale())
        assert artifact.schedule.meta.n_control_dates == N_CONTROL_DATES


def test_view_files_match_their_builders(demo_dir: Path) -> None:
    artifact = load_bundle(demo_dir / "bundles" / f"{BASE_ID}.json")
    densities = {well: 0.86 for well in artifact.schedule.meta.wells}
    exported = _read(demo_dir / "timeline.json")
    assert exported["steps"] == build_timeline(artifact, densities)["steps"]
    assert _read(demo_dir / "graph.json")["nodes"] == build_lambda_graph(artifact)["nodes"]
    assert _read(demo_dir / "npv.json")["wells"] == build_npv_by_well(artifact)["wells"]


def test_scenario_index_has_exactly_one_submitted(demo_dir: Path) -> None:
    bundles = [demo_dir / "bundles" / f"{name}.json" for name in (BASE_ID, WHATIF_ID)]
    index = build_scenario_index(bundles)
    assert index["submitted"] == BASE_ID
    assert [entry["id"] for entry in index["scenarios"]] == [BASE_ID, WHATIF_ID]
    whatif = next(e for e in index["scenarios"] if e["id"] == WHATIF_ID)
    assert whatif["npv_methodology"] is None


def test_what_if_scenario_differs_from_the_base(demo_dir: Path) -> None:
    base = _read(demo_dir / "npv.json")
    whatif = _read(demo_dir / WHATIF_ID / "npv.json")
    assert base["npv_methodology"] != whatif["npv_methodology"]


def test_demo_meta_is_honest_about_being_synthetic() -> None:
    meta = demo_meta("timeline")
    assert meta["provenance"] == DEMO_PROVENANCE
    assert meta["synthetic"] is True
    assert "не результат расчёта" in meta["notice_ru"]
