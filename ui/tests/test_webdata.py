import json
from pathlib import Path
from typing import Any

import pytest

from ui.deck import load_completions
from ui.webdata import build_wells_data, export_wells_json, occupied_k_values, split_layers

from conftest import missing_reason, model_z_schedule

DECK_PATH: Path | None = model_z_schedule()

pytestmark = pytest.mark.skipif(
    DECK_PATH is None, reason=missing_reason("Model_Z_sch.inc")
)
EXPECTED_WELLS: int = 103


@pytest.fixture(scope="module")
def data() -> dict[str, Any]:
    return build_wells_data(DECK_PATH)


def test_wells_count(data: dict[str, Any]) -> None:
    assert len(data["wells"]) == EXPECTED_WELLS
    assert len({well["id"] for well in data["wells"]}) == EXPECTED_WELLS


def test_every_well_has_layers(data: dict[str, Any]) -> None:
    for well in data["wells"]:
        assert well["layers"], well["id"]
        assert set(well["layers"]) <= {1, 2}, well["id"]
        assert well["completions"], well["id"]


def test_layers_cover_all_occupied_k(data: dict[str, Any]) -> None:
    occupied = occupied_k_values(load_completions(DECK_PATH))
    layer1, layer2 = data["layers"]
    assert layer1["k_max"] < layer2["k_min"]
    covered = set(range(layer1["k_min"], layer1["k_max"] + 1)) | set(
        range(layer2["k_min"], layer2["k_max"] + 1)
    )
    assert set(occupied) <= covered


def test_layer_assignment_matches_intervals(data: dict[str, Any]) -> None:
    layer1, layer2 = data["layers"]
    for well in data["wells"]:
        in_layer1 = any(k1 <= layer1["k_max"] for k1, _ in well["completions"])
        in_layer2 = any(k2 >= layer2["k_min"] for _, k2 in well["completions"])
        expected = [layer for layer, hit in ((1, in_layer1), (2, in_layer2)) if hit]
        assert well["layers"] == expected, well["id"]


def test_split_layers_prefers_widest_gap() -> None:
    assert split_layers([1, 2, 3, 7, 8]) == (3, 7)
    assert split_layers([1, 2, 4, 5, 9, 10]) == (5, 9)
    assert split_layers([1, 2, 3, 4]) == (2, 3)


def test_export_writes_parseable_json(tmp_path: Path) -> None:
    out = export_wells_json(DECK_PATH, tmp_path / "wells.json")
    assert out.exists()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert len(parsed["wells"]) == EXPECTED_WELLS
    assert parsed["grid"] == {"ni": 91, "nj": 102, "nk": 59}
