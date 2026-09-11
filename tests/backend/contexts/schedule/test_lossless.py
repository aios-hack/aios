
from datetime import date, timedelta

import pytest

from backend.core.contracts import ControlEvent, FixedDeckEvent, T0
from backend.domain.schedule import LosslessEmitter, ScheduleParseError, parse_schedule

from conftest import missing_reason, model_z_schedule


MODEL_Z_SCHEDULE = model_z_schedule()

pytestmark = pytest.mark.skipif(
    MODEL_Z_SCHEDULE is None,
    reason=missing_reason("дек Model_Z"),
)


def test_model_z_round_trip_and_fixed_layer() -> None:
    source = MODEL_Z_SCHEDULE.read_bytes()

    parsed = parse_schedule(source)

    assert LosslessEmitter.emit(parsed) == source
    assert len(parsed.dates) == 371
    assert parsed.dates[parsed.t0_deck_date_index] == T0
    assert parsed.t0_deck_date_index == 146

    compdat_blocks = [
        block
        for block in parsed.fixed_blocks
        if block.keyword in ("COMPDAT", "COMPDATMD")
    ]
    wpimult_blocks = [block for block in parsed.fixed_blocks if block.keyword == "WPIMULT"]
    expected_completion_blocks = [
        block
        for block in parsed.blocks
        if block.keyword in ("COMPDAT", "COMPDATMD")
        and block.control_step is not None
    ]
    expected_wpimult_blocks = [
        block
        for block in parsed.blocks
        if block.keyword == "WPIMULT" and block.control_step is not None
    ]
    assert compdat_blocks == expected_completion_blocks
    assert wpimult_blocks == expected_wpimult_blocks
    if wpimult_blocks:
        assert wpimult_blocks[-1].event_date.isoformat() == "2025-05-01"

    compdat_events = [
        event
        for event in parsed.fixed_deck_events
        if event.operator in ("COMPDAT", "COMPDATMD")
    ]
    wpimult_events = [
        event for event in parsed.fixed_deck_events if event.operator == "WPIMULT"
    ]
    commissioning_events = [
        event
        for event in parsed.fixed_deck_events
        if event.operator in ("WCONPROD", "WCONINJE")
    ]
    assert bool(compdat_events) == bool(compdat_blocks)
    assert bool(wpimult_events) == bool(wpimult_blocks)
    assert commissioning_events
    assert all(isinstance(event, FixedDeckEvent) for event in parsed.fixed_deck_events)
    assert all(isinstance(event, ControlEvent) for event in parsed.control_events)
    source_completion_operators = {
        operator
        for operator in ("COMPDAT", "COMPDATMD")
        if f"\n{operator}\n".encode() in source
    }
    parsed_completion_operators = {
        event.operator
        for event in parsed.fixed_deck_events
        if event.operator in ("COMPDAT", "COMPDATMD")
    }
    assert parsed_completion_operators == source_completion_operators


def test_unclosed_known_block_is_rejected() -> None:
    with pytest.raises(ScheduleParseError, match="блок не закрыт"):
        parse_schedule(b"DATES\n 01 JAN 2007 /\n")


def test_terminal_wcon_is_lossless_but_not_a_control_event() -> None:
    start = date(2007, 1, 1)
    chunks: list[bytes] = []
    for step in range(225):
        current = start + timedelta(days=step)
        chunks.append(
            f"DATES\n {current.day:02d} {current.strftime('%b').upper()} "
            f"{current.year} /\n/\n".encode()
        )
        if step in (0, 224):
            value = 10.0 if step == 0 else 20.0
            chunks.append(
                b"WCONPROD\n"
                + f" 'P1' 'OPEN' 'LRAT' 1* 1* 1* {value} /\n".encode()
                + b"/\n"
            )
    source = b"".join(chunks)

    parsed = parse_schedule(source)

    terminal = [block for block in parsed.blocks if block.control_step == 224][-1]
    assert terminal.keyword == "WCONPROD"
    assert terminal.control_events == ()
    assert parsed.control_events == ()
    assert LosslessEmitter.emit(parsed) == source
