from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.contracts import Schedule, ScheduleMeta
from backend.domain.schedule import parse_schedule
from backend.contexts.reservoir.infrastructure.opm_deck import (
    DIAGNOSTIC_MARKER_NAME,
    OpmDeckEmitter,
)
from backend.contexts.reservoir.infrastructure.summary import (
    REGION_MARKUP_KEYWORD,
    REGION_PRESSURE_KEY,
    REGION_REPORT_KEYWORD,
    SummaryPlanError,
    _expand_integers,
    _keyword_payload,
    build_region_plan,
    render_region_report_array,
    render_region_summary_include,
)

from tests.support.backend.environment import missing_reason, model_z_dir

MODEL_Z = model_z_dir()

pytestmark = pytest.mark.skipif(
    MODEL_Z is None, reason=missing_reason("каталог Model_Z")
)


def _baseline_schedule(emitter: OpmDeckEmitter) -> Schedule:
    parsed = parse_schedule((MODEL_Z / "Model_Z_sch.inc").read_bytes())
    return Schedule(
        meta=ScheduleMeta(wells=emitter.source_wells, provenance="Model_Z baseline"),
        initial_state={},
        fixed_deck_events=parsed.fixed_deck_events,
        control_events=parsed.control_events,
    )


def test_fipnum_is_assembled_from_the_fip_zone_markup_cell_by_cell() -> None:
    plan = build_region_plan(MODEL_Z)
    source = _expand_integers(
        _keyword_payload(
            (MODEL_Z / "Model_Z_regs.inc").read_bytes(),
            REGION_MARKUP_KEYWORD.encode("ascii"),
        ),
        REGION_MARKUP_KEYWORD,
    )

    assert plan.source_keyword == REGION_MARKUP_KEYWORD
    assert plan.report_keyword == REGION_REPORT_KEYWORD
    assert plan.values == source

    nx, ny, nz = plan.dimens
    assert len(plan.values) == nx * ny * nz

    emitted = render_region_report_array(plan)
    restored = _expand_integers(
        _keyword_payload(emitted, REGION_REPORT_KEYWORD.encode("ascii")),
        REGION_REPORT_KEYWORD,
    )
    assert restored == source


def test_rpr_is_requested_for_every_region_present_in_the_markup() -> None:
    plan = build_region_plan(MODEL_Z)

    assert plan.regions == (1, 2, 3, 4, 5)
    assert set(plan.regions) == {value for value in plan.values if value > 0}
    assert 0 not in plan.regions

    rendered = render_region_summary_include(plan).decode("ascii")
    lines = [line.strip() for line in rendered.splitlines() if line.strip()]
    assert lines[0] == REGION_PRESSURE_KEY
    assert lines[-1] == "/"
    assert tuple(int(item) for item in lines[1:-1]) == plan.regions


def test_missing_region_markup_is_an_error_not_an_empty_plan(tmp_path: Path) -> None:
    (tmp_path / "Model_Z.data").write_bytes(b"DIMENS\n 2 2 2 /\n")
    (tmp_path / "Model_Z_regs.inc").write_bytes(b"PVTNUM\n 8*1 /\n")

    with pytest.raises(SummaryPlanError) as error:
        build_region_plan(tmp_path)
    assert REGION_MARKUP_KEYWORD in str(error.value)


def test_diagnostic_deck_carries_fipnum_and_rpr_and_is_marked(tmp_path: Path) -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    schedule = _baseline_schedule(emitter)
    artifact = emitter.emit(schedule, tmp_path / "diagnostic", diagnostic_regions=True)

    assert artifact.diagnostic
    assert artifact.region_plan is not None
    assert artifact.region_plan.regions == (1, 2, 3, 4, 5)

    marker = artifact.diagnostic_marker_file
    assert marker is not None
    assert marker.name == DIAGNOSTIC_MARKER_NAME
    assert marker.is_file()
    assert "не идёт в сдачу" in marker.read_text(encoding="utf-8")

    assert artifact.regions_file is not None
    regions_raw = artifact.regions_file.read_bytes()
    assert b"\n" + REGION_REPORT_KEYWORD.encode("ascii") + b"\n" in regions_raw
    restored = _expand_integers(
        _keyword_payload(regions_raw, REGION_REPORT_KEYWORD.encode("ascii")),
        REGION_REPORT_KEYWORD,
    )
    assert restored == artifact.region_plan.values

    summary_raw = artifact.summary_file.read_bytes()
    assert b"\n" + REGION_PRESSURE_KEY.encode("ascii") + b"\n" in summary_raw
    requested = _expand_integers(
        _keyword_payload(summary_raw, REGION_PRESSURE_KEY.encode("ascii")),
        REGION_PRESSURE_KEY,
    )
    assert tuple(sorted(requested)) == artifact.region_plan.regions

    assert artifact.data_file.read_bytes().startswith(b"-- AIOS DIAGNOSTIC DECK")
    assert b"NOT FOR SUBMISSION" in summary_raw


def test_submitted_deck_stays_free_of_the_diagnostic_arrays(tmp_path: Path) -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    schedule = _baseline_schedule(emitter)
    submitted = emitter.emit(schedule, tmp_path / "submitted")
    diagnostic = emitter.emit(
        schedule, tmp_path / "diagnostic", diagnostic_regions=True
    )

    assert not submitted.diagnostic
    assert submitted.region_plan is None
    assert submitted.regions_file is None
    assert submitted.diagnostic_marker_file is None
    assert not (tmp_path / "submitted" / DIAGNOSTIC_MARKER_NAME).exists()

    submitted_regions = (tmp_path / "submitted" / "Model_Z_regs.inc").read_bytes()
    assert b"\n" + REGION_REPORT_KEYWORD.encode("ascii") + b"\n" not in submitted_regions
    submitted_summary = submitted.summary_file.read_bytes()
    assert b"\n" + REGION_PRESSURE_KEY.encode("ascii") + b"\n" not in submitted_summary
    assert b"NOT FOR SUBMISSION" not in submitted_summary
    assert not submitted.data_file.read_bytes().startswith(b"-- AIOS DIAGNOSTIC")

    assert (
        diagnostic.schedule_file.read_bytes() == submitted.schedule_file.read_bytes()
    )
    assert diagnostic.content_hash_opm != submitted.content_hash_opm
