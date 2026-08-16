from datetime import date

import pytest

from contracts import (
    Availability,
    OperatingStatus,
    Role,
    T0,
    WellState,
)
from schedule import (
    Conversion,
    ReplayError,
    build_schedule,
    deck_well_axis,
    history_blocks,
    parse_schedule,
    replay,
    replay_initial_state,
)
from schedule.lossless import LosslessBlock, ParsedSchedule
from schedule.replay import _Fund, _apply_record

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
def parsed(deck_bytes: bytes) -> ParsedSchedule:
    return parse_schedule(deck_bytes)


@pytest.fixture(scope="module")
def wells(deck_bytes: bytes) -> tuple[str, ...]:
    return deck_well_axis(deck_bytes)


@pytest.fixture(scope="module")
def result(parsed: ParsedSchedule, wells: tuple[str, ...]):
    return replay(parsed, wells)


def test_replay_covers_whole_well_axis(result, wells: tuple[str, ...]) -> None:
    assert set(result.state) == set(wells)
    assert len(result.state) == len(wells)
    assert tuple(result.state) == wells


def test_availability_split_matches_card(result, wells: tuple[str, ...]) -> None:
    assert len(result.commissioned) == 81
    assert len(result.not_commissioned) == 22
    assert len(result.commissioned) + len(result.not_commissioned) == len(wells)


def test_december_2006_slice_matches_card(result) -> None:
    producers = [
        well
        for well in result.commissioned
        if result.state[well].role is Role.PROD
    ]
    injectors = [
        well
        for well in result.commissioned
        if result.state[well].role is Role.INJ
    ]

    assert len(producers) == 58
    assert len(injectors) == 23
    assert sum(result.state[well].setpoint for well in producers) == 1505.0
    assert sum(result.state[well].setpoint for well in injectors) == 1495.0


def test_conversions_inside_history_are_counted(result) -> None:
    assert len(result.conversions) == 20
    assert all(conversion.event_date < T0 for conversion in result.conversions)
    assert len({conversion.well for conversion in result.conversions}) == len(
        result.conversions
    )


def test_history_and_horizon_conversions_sum_to_card_total(
    result, parsed: ParsedSchedule, deck_bytes: bytes
) -> None:
    schedule = build_schedule(parsed, deck_bytes)
    horizon = [
        event for event in schedule.control_events if event.kind.name == "CONVERT_INJ"
    ]

    assert len(horizon) == 10
    assert len(result.conversions) + len(horizon) == 30


def test_converted_wells_end_history_as_injectors(result) -> None:
    for conversion in result.conversions:
        state = result.state[conversion.well]
        assert state.availability is Availability.AVAILABLE
        assert state.role is Role.INJ


def test_not_commissioned_states_are_normalized(result) -> None:
    for well in result.not_commissioned:
        state = result.state[well]

        assert state.availability is Availability.NOT_COMMISSIONED
        assert state.role is Role.NONE
        assert state.operating_status is OperatingStatus.SHUT
        assert state.setpoint == 0.0


def test_commissioned_states_carry_role_and_setpoint(result) -> None:
    for well in result.commissioned:
        state = result.state[well]

        assert state.availability is Availability.AVAILABLE
        assert state.role in (Role.PROD, Role.INJ)
        assert state.operating_status in (OperatingStatus.OPEN, OperatingStatus.SHUT)
        assert state.setpoint >= 0.0


def test_prefix_is_strictly_before_t0(parsed: ParsedSchedule) -> None:
    blocks = history_blocks(parsed)

    assert blocks
    assert all(block.event_date is not None for block in blocks)
    assert max(block.event_date for block in blocks) < T0


def test_event_exactly_on_t0_is_excluded_from_history(
    parsed: ParsedSchedule, wells: tuple[str, ...], result
) -> None:
    at_t0 = [
        block
        for block in parsed.blocks
        if block.keyword in ("WCONPROD", "WCONINJE") and block.event_date == T0
    ]
    assert at_t0

    history = history_blocks(parsed)
    assert not any(block.event_date == T0 for block in history)

    shifted = replay(parsed, wells, t0=date(2007, 2, 1))
    assert len(shifted.commissioned) > len(result.commissioned)
    assert shifted.applied_blocks > result.applied_blocks


def test_wells_first_appearing_at_t0_stay_not_commissioned(
    parsed: ParsedSchedule, result
) -> None:
    first_seen: dict[str, object] = {}
    for block in parsed.blocks:
        if block.keyword not in ("WCONPROD", "WCONINJE"):
            continue
        for line in block.raw.splitlines()[1:-1]:
            body = line.split(b"--", 1)[0].strip()
            if not body:
                continue
            well = body.split(b"'")[1].decode("ascii")
            first_seen.setdefault(well, block.event_date)

    born_at_t0 = [well for well, seen in first_seen.items() if seen == T0]

    assert born_at_t0
    for well in born_at_t0:
        assert result.state[well].availability is Availability.NOT_COMMISSIONED


def test_replay_is_deterministic(parsed: ParsedSchedule, wells: tuple[str, ...]) -> None:
    first = replay(parsed, wells)
    second = replay(parsed, wells)

    assert first.state == second.state
    assert first.conversions == second.conversions
    assert first.commissioned == second.commissioned
    assert first.not_commissioned == second.not_commissioned


def test_replay_does_not_depend_on_axis_order(
    parsed: ParsedSchedule, wells: tuple[str, ...], result
) -> None:
    reversed_axis = tuple(reversed(wells))
    shuffled = replay(parsed, reversed_axis)

    assert shuffled.state == result.state
    assert tuple(shuffled.state) == reversed_axis
    assert set(shuffled.commissioned) == set(result.commissioned)
    assert set(shuffled.not_commissioned) == set(result.not_commissioned)
    assert shuffled.conversions == result.conversions


def test_replay_is_reread_stable(deck_bytes: bytes, wells: tuple[str, ...], result) -> None:
    reparsed = parse_schedule(deck_bytes)
    again = replay(reparsed, wells)

    assert again.state == result.state
    assert again.conversions == result.conversions


def test_replay_rejects_wells_outside_axis(parsed: ParsedSchedule) -> None:
    with pytest.raises(ReplayError, match="вне оси WELSPECS"):
        replay(parsed, ("1",))


def test_history_order_defines_last_setpoint() -> None:
    fund = _Fund()
    _apply_record(
        fund,
        "WCONPROD",
        ("7", "OPEN", "LRAT", "1*", "1*", "1*", "10.0", "1*", "50"),
        date(2000, 1, 1),
    )
    _apply_record(
        fund,
        "WCONPROD",
        ("7", "SHUT", "LRAT", "1*", "1*", "1*", "25.0", "1*", "50"),
        date(2001, 1, 1),
    )

    state = fund.wells["7"].freeze()

    assert state == WellState(
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.SHUT,
        setpoint=25.0,
    )


def test_conversion_is_recorded_once_per_transition() -> None:
    fund = _Fund()
    _apply_record(
        fund,
        "WCONPROD",
        ("7", "OPEN", "LRAT", "1*", "1*", "1*", "10.0", "1*", "50"),
        date(2000, 1, 1),
    )
    _apply_record(
        fund, "WCONINJE", ("7", "WATER", "OPEN", "RATE", "60.0"), date(2001, 1, 1)
    )
    _apply_record(
        fund, "WCONINJE", ("7", "WATER", "OPEN", "RATE", "80.0"), date(2002, 1, 1)
    )

    assert fund.conversions == [Conversion(well="7", event_date=date(2001, 1, 1))]
    assert fund.wells["7"].freeze().role is Role.INJ
    assert fund.wells["7"].freeze().setpoint == 80.0


def test_first_appearance_commissions_the_well() -> None:
    fund = _Fund()
    _apply_record(
        fund, "WCONINJE", ("9", "WATER", "SHUT", "RATE", "0.0"), date(1999, 3, 1)
    )

    state = fund.wells["9"]

    assert state.availability is Availability.AVAILABLE
    assert state.commissioned_at == date(1999, 3, 1)


def test_malformed_prod_record_is_rejected() -> None:
    fund = _Fund()

    with pytest.raises(ReplayError, match="ожидается режим LRAT"):
        _apply_record(
            fund, "WCONPROD", ("7", "OPEN", "ORAT", "1*", "1*", "1*", "10.0"), T0
        )


def test_malformed_inje_record_is_rejected() -> None:
    fund = _Fund()

    with pytest.raises(ReplayError, match="фаза WATER"):
        _apply_record(fund, "WCONINJE", ("7", "GAS", "OPEN", "RATE", "60.0"), T0)


def test_unknown_status_is_rejected() -> None:
    fund = _Fund()

    with pytest.raises(ReplayError, match="неизвестный статус"):
        _apply_record(
            fund,
            "WCONPROD",
            ("7", "AUTO", "LRAT", "1*", "1*", "1*", "10.0"),
            date(2000, 1, 1),
        )


def test_non_numeric_setpoint_is_rejected() -> None:
    fund = _Fund()

    with pytest.raises(ReplayError, match="не является числом"):
        _apply_record(
            fund,
            "WCONPROD",
            ("7", "OPEN", "LRAT", "1*", "1*", "1*", "много"),
            date(2000, 1, 1),
        )


def test_block_without_date_is_rejected(wells: tuple[str, ...]) -> None:
    block = LosslessBlock(
        keyword="WCONPROD",
        raw=b"WCONPROD\n 'X' 'OPEN' 'LRAT' 1* 1* 1* 10.0 /\n/\n",
        deck_date_index=None,
        event_date=None,
        control_step=None,
    )
    parsed = ParsedSchedule(
        chunks=(block,),
        blocks=(block,),
        dates=(date(2000, 1, 1),),
        t0_deck_date_index=0,
        fixed_deck_events=(),
        control_events=(),
    )

    assert history_blocks(parsed) == ()
    assert replay(parsed, wells).applied_blocks == 0


def test_build_schedule_uses_replay(
    parsed: ParsedSchedule, deck_bytes: bytes, wells: tuple[str, ...], result
) -> None:
    schedule = build_schedule(parsed, deck_bytes)

    assert schedule.initial_state == result.state
    assert schedule.initial_state == replay_initial_state(parsed, wells)
