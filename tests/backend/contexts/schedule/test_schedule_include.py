from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from backend.core.contracts import (
    ControlEvent,
    EventKind,
    Schedule,
    ScheduleMeta,
    hash_schedule,
)
from backend.domain.schedule import build_schedule, parse_schedule
from backend.contexts.schedule.application.emit import (
    ScheduleEmitError,
    ScheduleRoundTripReport,
    verify_schedule_round_trip,
)
from backend.infrastructure.opm import (
    EmittedSchedule,
    OpmDeckEmitter,
    render_schedule_include,
)

from tests.support.backend.environment import missing_reason, model_z_dir

MODEL_Z = model_z_dir()

pytestmark = pytest.mark.skipif(
    MODEL_Z is None, reason=missing_reason("каталог Model_Z")
)


@pytest.fixture(scope="module")
def emitter() -> OpmDeckEmitter:
    return OpmDeckEmitter(MODEL_Z)


@pytest.fixture(scope="module")
def plan(emitter: OpmDeckEmitter) -> Schedule:
    source = (MODEL_Z / "Model_Z_sch.inc").read_bytes()
    baseline = build_schedule(parse_schedule(source), source, provenance="Model_Z")
    rendered = render_schedule_include(baseline, MODEL_Z)
    expressible = build_schedule(
        parse_schedule(rendered.raw), rendered.raw, provenance="Model_Z"
    )
    return Schedule(
        meta=ScheduleMeta(wells=emitter.source_wells, provenance="Model_Z"),
        initial_state=expressible.initial_state,
        fixed_deck_events=expressible.fixed_deck_events,
        control_events=expressible.control_events,
    )


def _first_setpoint_index(events: tuple[ControlEvent, ...]) -> int:
    for index, event in enumerate(events):
        if event.kind is EventKind.SET_LRAT and event.value:
            return index
    raise AssertionError("в расписании нет ни одной ненулевой уставки LRAT")


def test_render_schedule_include_matches_the_full_deck_byte_for_byte(
    emitter: OpmDeckEmitter, plan: Schedule, tmp_path: Path
) -> None:
    artifact = emitter.emit(plan, tmp_path / "deck")
    rendered = render_schedule_include(plan, MODEL_Z)

    assert isinstance(rendered, EmittedSchedule)
    assert rendered.raw == artifact.schedule_file.read_bytes()
    assert rendered.model_dir == emitter.model_dir
    assert rendered.opm_schedule_source == emitter.opm_schedule_source
    assert len(rendered.content_hash) == 64


def test_content_hash_is_sha256_of_the_returned_bytes(plan: Schedule) -> None:
    rendered = render_schedule_include(plan, MODEL_Z)
    assert rendered.content_hash == hashlib.sha256(rendered.raw).hexdigest()


def test_rendering_is_deterministic_for_the_same_schedule(plan: Schedule) -> None:
    first = render_schedule_include(plan, MODEL_Z)
    second = render_schedule_include(plan, str(MODEL_Z))
    assert first.raw == second.raw
    assert first.content_hash == second.content_hash


def test_round_trip_holds_on_a_valid_schedule(plan: Schedule) -> None:
    rendered = render_schedule_include(plan, MODEL_Z)
    report = verify_schedule_round_trip(plan, rendered.raw)

    assert isinstance(report, ScheduleRoundTripReport)
    assert report.ok, report.format()
    assert report.divergence is None
    assert report.source_hash == report.reparsed_hash == hash_schedule(plan)
    assert report.n_bytes == len(rendered.raw)
    assert report.content_hash == rendered.content_hash
    report.raise_if_broken()


def test_changing_one_event_breaks_the_round_trip(plan: Schedule) -> None:
    rendered = render_schedule_include(plan, MODEL_Z)
    index = _first_setpoint_index(plan.control_events)
    original = plan.control_events[index]
    tampered_events = list(plan.control_events)
    tampered_events[index] = dataclasses.replace(original, value=original.value + 7.0)
    tampered = dataclasses.replace(plan, control_events=tuple(tampered_events))

    report = verify_schedule_round_trip(tampered, rendered.raw)

    assert not report.ok
    assert report.source_hash != report.reparsed_hash
    assert report.divergence is not None
    assert report.divergence.expected is not None
    assert report.divergence.actual is not None
    assert report.divergence.expected != report.divergence.actual
    message = report.format()
    assert "не сошёлся" in message
    assert "первое расхождение управляющего слоя" in message

    with pytest.raises(ScheduleEmitError) as raised:
        report.raise_if_broken()
    assert str(raised.value) == message


def test_a_tampered_schedule_renders_different_bytes(plan: Schedule) -> None:
    index = _first_setpoint_index(plan.control_events)
    original = plan.control_events[index]
    tampered_events = list(plan.control_events)
    tampered_events[index] = dataclasses.replace(original, value=original.value + 7.0)
    tampered = dataclasses.replace(plan, control_events=tuple(tampered_events))

    clean = render_schedule_include(plan, MODEL_Z)
    dirty = render_schedule_include(tampered, MODEL_Z)

    assert dirty.raw != clean.raw
    assert dirty.content_hash != clean.content_hash
    verify_schedule_round_trip(tampered, dirty.raw).raise_if_broken()


def test_unparsable_bytes_are_reported_not_silently_accepted(plan: Schedule) -> None:
    with pytest.raises(ScheduleEmitError):
        verify_schedule_round_trip(plan, b"DATES\n 01 JAN 2007 /\n")


def test_missing_model_dir_is_reported(plan: Schedule, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        render_schedule_include(plan, tmp_path)
