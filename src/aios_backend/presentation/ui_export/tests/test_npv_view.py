from __future__ import annotations

import json
from pathlib import Path

import pytest

from aios_backend.presentation.ui_export.fixtures import make_synthetic_artifact
from aios_backend.presentation.ui_export.npv_view import build_npv_by_well, export_npv_json


def test_values_taken_from_by_well_without_distortion() -> None:
    artifact = make_synthetic_artifact()
    data = build_npv_by_well(artifact)
    by_well = artifact.npv_table.by_well
    assert [row["well"] for row in data["wells"]] == sorted(by_well)
    for row in data["wells"]:
        items = by_well[row["well"]]
        assert row["with_allocated_tax"] == items.discounted_fcf
        assert row["pre_tax"] == items.discounted_fcf + items.income_tax * items.df


def test_both_variants_present_and_distinct() -> None:
    artifact = make_synthetic_artifact()
    data = build_npv_by_well(artifact)
    by_well = artifact.npv_table.by_well
    assert any(items.income_tax > 0 for items in by_well.values())
    for row in data["wells"]:
        assert {"well", "pre_tax", "with_allocated_tax"} <= set(row)
        items = by_well[row["well"]]
        if items.income_tax > 0:
            assert row["pre_tax"] != row["with_allocated_tax"]
            assert row["pre_tax"] - row["with_allocated_tax"] == pytest.approx(
                items.income_tax * items.df
            )


def test_totals_and_npv_methodology_passthrough() -> None:
    artifact = make_synthetic_artifact()
    data = build_npv_by_well(artifact)
    assert data["total"]["pre_tax"] == pytest.approx(
        sum(row["pre_tax"] for row in data["wells"])
    )
    assert data["total"]["with_allocated_tax"] == pytest.approx(
        sum(row["with_allocated_tax"] for row in data["wells"])
    )
    assert data["npv_methodology"] == artifact.npv_table.npv_methodology


def test_order_is_canonical_not_by_contribution() -> None:
    artifact = make_synthetic_artifact()
    wells = [row["well"] for row in build_npv_by_well(artifact)["wells"]]
    assert wells == sorted(artifact.npv_table.by_well)


def test_export_round_trip(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    out = export_npv_json(artifact, tmp_path / "npv.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == build_npv_by_well(artifact)
