from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from bridge import OpmDeckEmitter, OpmDeckError
from contracts import (
    OPM_CONNECTION_SUMMARY_KEYS,
    OPM_WELL_SUMMARY_KEYS,
    EventKind,
    Schedule,
    ScheduleMeta,
)
from schedule import parse_schedule


from conftest import missing_reason, model_z_dir

MODEL_Z = model_z_dir()
OPM_IMAGE = os.environ.get("OPM_FLOW_IMAGE", "openporousmedia/opmreleases:latest")

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


def _keyword_block(raw: bytes, keyword: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    start = next(index for index, line in enumerate(lines) if line.strip() == keyword)
    end = next(index for index in range(start + 1, len(lines)) if lines[index].strip() == b"/")
    return b"".join(lines[start : end + 1])


def test_emits_complete_model_z_without_changing_fixed_layer(tmp_path: Path) -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    artifact = emitter.emit(_baseline_schedule(emitter), tmp_path / "run-a")

    source = (MODEL_Z / "Model_Z_sch.inc").read_bytes()
    emitted = artifact.schedule_file.read_bytes()
    source_parsed = parse_schedule(source)
    emitted_parsed = parse_schedule(emitted)

    assert len(emitter.source_wells) == 103
    assert _keyword_block(emitted, b"WELSPECS") == _keyword_block(source, b"WELSPECS")
    assert emitted_parsed.fixed_deck_events == source_parsed.fixed_deck_events
    assert [
        block.raw for block in emitted_parsed.fixed_blocks if block.keyword == "WPIMULT"
    ] == [block.raw for block in source_parsed.fixed_blocks if block.keyword == "WPIMULT"]

    source_compdat = [
        (block.event_date, block.raw)
        for block in source_parsed.fixed_blocks
        if block.keyword == "COMPDAT"
    ]
    emitted_compdat = [
        (block.event_date, block.raw)
        for block in emitted_parsed.fixed_blocks
        if block.keyword == "COMPDAT"
    ]
    assert len(source_compdat) == 25
    assert emitted_compdat == source_compdat
    assert {event.control_step for event in emitted_parsed.control_events} == set(range(224))
    assert len(artifact.content_hash_opm) == 64
    assert artifact.data_file.is_file()
    assert artifact.summary_file.is_file()
    assert artifact.summary_plan.wells == emitter.source_wells
    assert len(artifact.summary_plan.connections) == 1368
    assert all(path.is_file() for path in artifact.input_files)

    summary = artifact.summary_file.read_bytes()
    for keyword in (*OPM_WELL_SUMMARY_KEYS, *OPM_CONNECTION_SUMMARY_KEYS):
        assert f"\n{keyword}\n".encode("ascii") in summary
    assert b"\nWOMT\n" not in summary
    assert b"\nWOMR\n" not in summary


def test_rejects_changed_fixed_layer(tmp_path: Path) -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    baseline = _baseline_schedule(emitter)
    changed = Schedule(
        meta=baseline.meta,
        initial_state=baseline.initial_state,
        fixed_deck_events=baseline.fixed_deck_events[:-1],
        control_events=baseline.control_events,
    )

    with pytest.raises(OpmDeckError, match="фиксированный слой"):
        emitter.emit(changed, tmp_path / "bad")


def test_replaces_organizer_controls_with_our_dense_layer(tmp_path: Path) -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    baseline = _baseline_schedule(emitter)
    changed_events = tuple(
        replace(event, value=46.0)
        if event.control_step == 0
        and event.well == "1"
        and event.kind is EventKind.SET_LRAT
        else event
        for event in baseline.control_events
    )
    changed = Schedule(
        meta=baseline.meta,
        initial_state=baseline.initial_state,
        fixed_deck_events=baseline.fixed_deck_events,
        control_events=changed_events,
    )

    artifact = emitter.emit(changed, tmp_path / "changed")
    emitted = parse_schedule(artifact.schedule_file.read_bytes())
    values = [
        event.value
        for event in emitted.control_events
        if event.control_step == 0
        and event.well == "1"
        and event.kind is EventKind.SET_LRAT
    ]

    assert values == [46.0]


def test_emitted_deck_is_read_by_real_opm_flow(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.fail("для приёмки задачи 2 требуется Docker с настоящим OPM Flow")

    emitter = OpmDeckEmitter(MODEL_Z)
    artifact = emitter.emit(_baseline_schedule(emitter), tmp_path / "opm-deck")
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{artifact.data_file.parent}:/model:ro",
            OPM_IMAGE,
            "flow",
            "/model/Model_Z.data",
            "--enable-dry-run=true",
            "--enable-terminal-output=false",
            "--output-dir=/tmp/opm-output",
            "--output-mode=none",
            "--parsing-strictness=low",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode == 0, result.stdout[-8000:]
    assert "Error:" not in result.stdout, result.stdout[-8000:]
