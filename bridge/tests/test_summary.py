from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from bridge import OpmDeckEmitter, build_summary_plan, render_summary_include
from contracts import (
    OPM_CONNECTION_SUMMARY_KEYS,
    OPM_WELL_SUMMARY_KEYS,
    SUMMARY_EXPORT_KEYS,
)


MODEL_Z = Path(__file__).resolve().parents[3] / "docs" / "models" / "Model_Z"


def _record_count(raw: bytes, keyword: str) -> int:
    lines = raw.splitlines()
    start = lines.index(keyword.encode("ascii"))
    end = lines.index(b"/", start + 1)
    return end - start - 1


def test_builds_complete_model_z_summary_plan() -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    plan = build_summary_plan(MODEL_Z, emitter.source_wells)

    assert plan.spec.export_keys == SUMMARY_EXPORT_KEYS
    assert plan.spec.opm_well_keys == OPM_WELL_SUMMARY_KEYS
    assert plan.spec.opm_connection_keys == OPM_CONNECTION_SUMMARY_KEYS
    assert len(plan.wells) == 103
    assert len(plan.connections) == 1368
    assert Counter(connection.pvt_region for connection in plan.connections) == {
        1: 1216,
        2: 152,
    }

    regions_by_well: dict[str, set[int]] = defaultdict(set)
    for connection in plan.connections:
        regions_by_well[connection.well].add(connection.pvt_region)
    assert Counter(map(len, regions_by_well.values())) == {1: 80, 2: 23}


def test_renders_only_supported_opm_vectors_for_every_axis_item() -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    plan = build_summary_plan(MODEL_Z, emitter.source_wells)

    first = render_summary_include(plan)
    second = render_summary_include(plan)

    assert first == second
    assert b"\nWOMT\n" not in first
    assert b"\nWOMR\n" not in first
    assert b"\nWMCTL\n" in first
    for keyword in OPM_WELL_SUMMARY_KEYS:
        assert _record_count(first, keyword) == 103
    for keyword in OPM_CONNECTION_SUMMARY_KEYS:
        assert _record_count(first, keyword) == 1368
