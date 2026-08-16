from pathlib import Path

import pytest

from contracts import T0, content_hash
from schedule import LosslessEmitter, parse_schedule
from schedule.emit import (
    WELLS_SCHEDULE_FILE_NAME,
    ScheduleEmitError,
    emit_from_deck,
    emit_to_file,
    emit_wells_schedule,
    round_trip,
)

from conftest import missing_reason, model_z_schedule

MODEL_Z_SCHEDULE = model_z_schedule()

pytestmark = pytest.mark.skipif(
    MODEL_Z_SCHEDULE is None,
    reason=missing_reason("дек Model_Z"),
)


@pytest.fixture(scope="module")
def deck_bytes() -> bytes:
    return MODEL_Z_SCHEDULE.read_bytes()


@pytest.fixture(scope="module")
def parsed(deck_bytes: bytes):
    return parse_schedule(deck_bytes)


def test_round_trip_is_byte_identical_on_the_real_deck(deck_bytes: bytes) -> None:
    report = round_trip(deck_bytes)
    assert report.byte_identical
    assert report.ok, report.format()
    assert report.first_difference is None
    assert report.n_emitted_bytes == report.n_source_bytes == len(deck_bytes)
    assert report.emitted_hash == report.source_hash == content_hash(deck_bytes)
    report.raise_if_broken()


def test_reparsing_the_emitted_file_gives_the_same_schedule(deck_bytes: bytes) -> None:
    report = round_trip(deck_bytes)
    assert report.control_events_match
    assert report.fixed_events_match
    assert report.dates_match


def test_emit_is_full_not_sparse_by_default(parsed, deck_bytes: bytes) -> None:
    emitted = emit_wells_schedule(parsed)
    assert emitted.sparse is False
    assert emitted.raw == deck_bytes
    assert emitted.stats.dropped_control_blocks == 0


def test_full_emit_carries_a_wconprod_block_on_every_step(parsed) -> None:
    emitted = emit_wells_schedule(parsed)
    assert emitted.stats.n_dates == 371
    assert emitted.stats.n_wconprod_blocks == 370
    assert emitted.stats.n_wconinje_blocks == 338
    assert emitted.stats.n_fund_blocks == 708


def test_fixed_events_stay_on_their_dates(parsed) -> None:
    emitted = emit_wells_schedule(parsed)
    assert emitted.stats.n_compdat_blocks == 60
    assert emitted.stats.n_wpimult_blocks == 1
    assert emitted.stats.n_fixed_blocks == 61

    reparsed = parse_schedule(emitted.raw)
    source_fixed = [
        (block.keyword, block.event_date, block.raw)
        for block in parsed.fixed_blocks
    ]
    emitted_fixed = [
        (block.keyword, block.event_date, block.raw)
        for block in reparsed.fixed_blocks
    ]
    assert emitted_fixed == source_fixed
    assert len([item for item in source_fixed if item[0] == "COMPDAT"]) == 25
    wpimult = [item for item in source_fixed if item[0] == "WPIMULT"]
    assert len(wpimult) == 1
    assert wpimult[0][1].isoformat() == "2025-05-01"


def test_commissioning_of_22_wells_survives_the_emit(parsed) -> None:
    emitted = emit_wells_schedule(parsed)
    reparsed = parse_schedule(emitted.raw)
    commissioning = [
        event
        for event in reparsed.fixed_deck_events
        if event.operator in ("WCONPROD", "WCONINJE")
    ]
    assert len({event.well for event in commissioning}) == 22
    assert commissioning == [
        event
        for event in parsed.fixed_deck_events
        if event.operator in ("WCONPROD", "WCONINJE")
    ]


def test_sparse_is_a_flag_and_drops_only_repeated_control_blocks(parsed) -> None:
    full = emit_wells_schedule(parsed)
    sparse = emit_wells_schedule(parsed, sparse=True)
    assert sparse.sparse is True
    assert sparse.stats.dropped_control_blocks > 0
    assert sparse.stats.n_bytes < full.stats.n_bytes
    assert sparse.stats.n_compdat_blocks == full.stats.n_compdat_blocks
    assert sparse.stats.n_wpimult_blocks == full.stats.n_wpimult_blocks
    assert sparse.stats.n_dates == full.stats.n_dates


def test_sparse_output_is_still_parsable_and_keeps_the_dates(parsed) -> None:
    sparse = emit_wells_schedule(parsed, sparse=True)
    reparsed = parse_schedule(sparse.raw)
    assert reparsed.dates == parsed.dates
    assert reparsed.t0_deck_date_index == parsed.t0_deck_date_index
    assert reparsed.dates[reparsed.t0_deck_date_index] == T0
    assert reparsed.fixed_deck_events == parsed.fixed_deck_events


def test_sparse_does_not_survive_byte_round_trip(parsed, deck_bytes: bytes) -> None:
    sparse = emit_wells_schedule(parsed, sparse=True)
    assert sparse.raw != deck_bytes


def test_emitted_file_is_named_wells_schedule_inc(parsed, tmp_path: Path) -> None:
    path, emitted = emit_to_file(parsed, tmp_path)
    assert path.name == WELLS_SCHEDULE_FILE_NAME
    assert path.parent == tmp_path
    assert path.read_bytes() == emitted.raw


def test_emit_from_deck_writes_the_source_bytes(
    tmp_path: Path, deck_bytes: bytes
) -> None:
    path, emitted, report = emit_from_deck(MODEL_Z_SCHEDULE, tmp_path)
    assert path.read_bytes() == deck_bytes
    assert report.byte_identical
    assert emitted.content_hash == content_hash(deck_bytes)
    assert emitted.sparse is False


def test_emit_from_deck_supports_the_sparse_flag(tmp_path: Path) -> None:
    path, emitted, report = emit_from_deck(
        MODEL_Z_SCHEDULE, tmp_path, sparse=True, file_name="sparse.inc"
    )
    assert report.byte_identical
    assert emitted.sparse is True
    assert path.name == "sparse.inc"
    assert emitted.stats.dropped_control_blocks > 0


def test_emitter_is_the_lossless_one_not_a_second_implementation(parsed) -> None:
    assert emit_wells_schedule(parsed).raw == LosslessEmitter.emit(parsed)


def test_lossless_emit_preserves_even_unknown_bytes(deck_bytes: bytes) -> None:
    tampered = deck_bytes.replace(b"'GROUP'", b"'GROUb'", 1)
    report = round_trip(tampered)
    assert report.ok
    assert report.byte_identical


def test_broken_round_trip_is_reported_and_raised() -> None:
    from schedule.emit import RoundTripReport

    broken = RoundTripReport(
        byte_identical=False,
        source_hash="a" * 64,
        emitted_hash="b" * 64,
        n_source_bytes=10,
        n_emitted_bytes=9,
        first_difference=3,
        control_events_match=True,
        fixed_events_match=True,
        dates_match=True,
    )
    assert not broken.ok
    assert "не сошёлся" in broken.format()
    with pytest.raises(ScheduleEmitError):
        broken.raise_if_broken()


def test_unparsable_deck_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.inc"
    bad.write_bytes(b"DATES\n 01 JAN 2007 /\n")
    with pytest.raises(ScheduleEmitError):
        emit_from_deck(bad, tmp_path)
