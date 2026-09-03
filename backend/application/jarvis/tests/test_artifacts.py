from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from backend.application.jarvis.artifacts import (
    ArtifactError,
    ArtifactStore,
    SCENARIO_FILES,
)


def test_scenarios_listed(store: ArtifactStore) -> None:
    assert set(store.scenarios()) == {"base", "policy-plan", "whatif-injection-cut"}
    assert store.submitted() == "policy-plan"


def test_every_scenario_has_full_set(store: ArtifactStore, data_root: Path) -> None:
    for scenario in store.scenarios():
        directory = data_root / scenario
        for name in SCENARIO_FILES:
            assert (directory / f"{name}.json").is_file()


def test_base_index_shape(store: ArtifactStore) -> None:
    index = store.scenario("base")
    assert index.step_count() == 225
    assert len(index.by_well) == 103
    assert index.dates[0] == "2007-01-01"
    assert index.dates[-1] == "2025-09-01"
    assert index.provenance() == "model-z-base-run"


def test_well_index_covers_all_steps(store: ArtifactStore) -> None:
    index = store.scenario("base")
    rows = index.require_well("13")
    assert len(rows.steps) == 225
    assert rows.steps[0]["well"] == "13"


def test_npv_and_edges_indexed(store: ArtifactStore) -> None:
    index = store.scenario("base")
    assert len(index.npv_by_well) == 103
    assert index.npv_by_well["1"]["with_allocated_tax"] == pytest.approx(
        449123522.6185972
    )
    assert len(index.graph["edges"]) == 2375
    assert index.edges_by_well["1"][0]["weight"] >= index.edges_by_well["1"][-1]["weight"]


def test_step_for_date(store: ArtifactStore) -> None:
    index = store.scenario("base")
    assert index.step_for_date("2015-01-01") == 96
    assert index.dates[96] == "2015-01-01"


def test_unknown_well_raises_human_text(store: ArtifactStore) -> None:
    index = store.scenario("base")
    with pytest.raises(ArtifactError) as error:
        index.require_well("45")
    assert "well 45 is not in the stock" in str(error.value)


def test_unknown_step_raises(store: ArtifactStore) -> None:
    index = store.scenario("base")
    with pytest.raises(ArtifactError) as error:
        index.require_step(999)
    assert "step 999 does not exist" in str(error.value)


def test_unknown_scenario_raises(store: ArtifactStore) -> None:
    with pytest.raises(ArtifactError) as error:
        store.scenario("no-such-scenario")
    assert "no-such-scenario" in str(error.value)


def test_reread_on_mtime_change(tmp_path: Path, data_root: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    shutil.copy(data_root / "scenarios.json", root / "scenarios.json")
    shutil.copy(data_root / "wells.json", root / "wells.json")
    for name in SCENARIO_FILES:
        shutil.copy(data_root / "base" / f"{name}.json", root / f"{name}.json")
    store = ArtifactStore(root)
    first = store.scenario("base")
    assert first.step_count() == 225
    payload = json.loads((root / "timeline.json").read_text(encoding="utf-8"))
    payload["steps"] = payload["steps"][:10]
    (root / "timeline.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    stamp = time.time() + 10
    os.utime(root / "timeline.json", (stamp, stamp))
    second = store.scenario("base")
    assert second.step_count() == 10
