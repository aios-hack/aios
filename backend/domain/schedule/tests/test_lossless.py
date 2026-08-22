
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

    compdat_blocks = [block for block in parsed.fixed_blocks if block.keyword == "COMPDAT"]
    wpimult_blocks = [block for block in parsed.fixed_blocks if block.keyword == "WPIMULT"]
    assert len(compdat_blocks) == 25
    assert len(wpimult_blocks) == 1
    assert wpimult_blocks[0].event_date.isoformat() == "2025-05-01"

    compdat_events = [
        event for event in parsed.fixed_deck_events if event.operator == "COMPDAT"
    ]
    wpimult_events = [
        event for event in parsed.fixed_deck_events if event.operator == "WPIMULT"
    ]
    commissioning_events = [
        event
        for event in parsed.fixed_deck_events
        if event.operator in ("WCONPROD", "WCONINJE")
    ]
    assert len(compdat_events) == 117
    assert len(wpimult_events) == 7
    assert len(commissioning_events) == 22
    assert all(isinstance(event, FixedDeckEvent) for event in parsed.fixed_deck_events)
    assert all(isinstance(event, ControlEvent) for event in parsed.control_events)
    assert b"COMPDATMD" not in source
    assert all(event.operator != "COMPDATMD" for event in parsed.fixed_deck_events)


def test_unclosed_known_block_is_rejected() -> None:
    with pytest.raises(ScheduleParseError, match="блок не закрыт"):
        parse_schedule(b"DATES\n 01 JAN 2007 /\n")
