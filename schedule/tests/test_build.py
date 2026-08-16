
import pytest

from contracts import (
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    MAX_LRAT_M3_PER_DAY,
    OperatingStatus,
    Role,
    T0,
    WellState,
    hash_schedule,
)
from schedule import (
    ScheduleBuildError,
    build_schedule,
    canonical_control_events,
    deck_well_axis,
    detect_control_conflicts,
    load_schedule,
    parse_schedule,
    schedule_hash_parts,
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
def schedule(deck_bytes: bytes):
    return build_schedule(parse_schedule(deck_bytes), deck_bytes)


def test_horizon_numbers_come_from_deck(deck_bytes: bytes, schedule) -> None:
    parsed = parse_schedule(deck_bytes)
    expected_dates = len(parsed.dates) - parsed.t0_deck_date_index

    assert schedule.meta.t0 == T0
    assert schedule.meta.n_control_dates == expected_dates
    assert schedule.meta.n_intervals == expected_dates - 1
    assert schedule.meta.model == "Model_Z"


def test_well_axis_holds_full_fund_including_not_commissioned(
    deck_bytes: bytes, schedule
) -> None:
    axis = deck_well_axis(deck_bytes)

    assert schedule.meta.wells == axis
    assert len(schedule.initial_state) == len(axis)
    assert set(schedule.initial_state) == set(axis)

    not_commissioned = [
        well
        for well, state in schedule.initial_state.items()
        if state.availability is Availability.NOT_COMMISSIONED
    ]
    commissioned_inside = {
        event.well
        for event in schedule.fixed_deck_events
        if event.operator in ("WCONPROD", "WCONINJE")
    }

    assert set(not_commissioned) == commissioned_inside
    assert len(not_commissioned) == len(commissioned_inside)
    assert len(not_commissioned) < len(axis)


def test_not_commissioned_states_are_normalized(schedule) -> None:
    for state in schedule.initial_state.values():
        if state.availability is Availability.NOT_COMMISSIONED:
            assert state.role is Role.NONE
            assert state.operating_status is OperatingStatus.SHUT
            assert state.setpoint == 0.0
        else:
            assert state.role in (Role.PROD, Role.INJ)


def test_layers_are_split_by_operator(schedule) -> None:
    fixed_operators = {event.operator for event in schedule.fixed_deck_events}
    control_kinds = {event.kind for event in schedule.control_events}

    assert "COMPDAT" in fixed_operators
    assert "WPIMULT" in fixed_operators
    assert fixed_operators <= {"COMPDAT", "WPIMULT", "WCONPROD", "WCONINJE"}
    assert control_kinds <= {
        EventKind.SET_LRAT,
        EventKind.SET_RATE,
        EventKind.OPEN,
        EventKind.SHUT,
        EventKind.CONVERT_INJ,
    }
    assert all(isinstance(event, FixedDeckEvent) for event in schedule.fixed_deck_events)
    assert all(isinstance(event, ControlEvent) for event in schedule.control_events)


def test_compdat_inside_horizon_is_fixed_not_control(deck_bytes: bytes, schedule) -> None:
    parsed = parse_schedule(deck_bytes)
    compdat_blocks = [block for block in parsed.blocks if block.keyword == "COMPDAT"]
    inside = [block for block in compdat_blocks if block.control_step is not None]

    assert inside
    assert all(not block.control_events for block in inside)

    fixed_compdat = [
        event for event in schedule.fixed_deck_events if event.operator == "COMPDAT"
    ]
    assert len(fixed_compdat) == sum(len(block.fixed_deck_events) for block in inside)


def test_control_events_are_within_intervals(schedule) -> None:
    steps = {event.control_step for event in schedule.control_events}

    assert min(steps) == 0
    assert max(steps) == schedule.meta.n_intervals - 1
    assert all(0 <= step < schedule.meta.n_intervals for step in steps)


def test_canonical_order_is_semantic_not_alphabetical() -> None:
    events = [
        ControlEvent(control_step=3, well="7", kind=EventKind.OPEN),
        ControlEvent(control_step=3, well="7", kind=EventKind.SET_RATE, value=10.0),
        ControlEvent(control_step=3, well="7", kind=EventKind.CONVERT_INJ),
        ControlEvent(control_step=1, well="7", kind=EventKind.SET_LRAT, value=5.0),
    ]

    ordered = canonical_control_events(events)

    assert [event.kind for event in ordered] == [
        EventKind.SET_LRAT,
        EventKind.CONVERT_INJ,
        EventKind.SET_RATE,
        EventKind.OPEN,
    ]


def test_canonical_order_sorts_wells_numerically() -> None:
    events = [
        ControlEvent(control_step=0, well="10", kind=EventKind.SET_LRAT, value=1.0),
        ControlEvent(control_step=0, well="2", kind=EventKind.SET_LRAT, value=1.0),
    ]

    assert [event.well for event in canonical_control_events(events)] == ["2", "10"]


def test_exact_duplicates_are_removed() -> None:
    event = ControlEvent(control_step=0, well="1", kind=EventKind.SET_LRAT, value=42.0)

    assert canonical_control_events([event, event, event]) == (event,)


def test_conflicting_events_are_rejected() -> None:
    events = [
        ControlEvent(control_step=0, well="1", kind=EventKind.SET_LRAT, value=42.0),
        ControlEvent(control_step=0, well="1", kind=EventKind.SET_LRAT, value=43.0),
    ]

    conflicts = detect_control_conflicts(events)
    assert len(conflicts) == 1
    assert conflicts[0].well == "1"
    assert set(conflicts[0].values) == {42.0, 43.0}

    with pytest.raises(ScheduleBuildError, match="конфликтующие"):
        canonical_control_events(events)


def test_lrat_ceiling_is_enforced_by_constructor() -> None:
    with pytest.raises(ValueError, match="превышает потолок"):
        ControlEvent(
            control_step=0,
            well="1",
            kind=EventKind.SET_LRAT,
            value=MAX_LRAT_M3_PER_DAY + 1.0,
        )

    ControlEvent(
        control_step=0, well="1", kind=EventKind.SET_LRAT, value=MAX_LRAT_M3_PER_DAY
    )


def test_real_deck_has_no_lrat_ceiling_violation(schedule) -> None:
    setpoints = [
        event.value
        for event in schedule.control_events
        if event.kind is EventKind.SET_LRAT and event.value is not None
    ]

    assert setpoints
    assert max(setpoints) <= MAX_LRAT_M3_PER_DAY


def test_hash_is_three_part_and_deterministic(deck_bytes: bytes, schedule) -> None:
    rebuilt = build_schedule(parse_schedule(deck_bytes), deck_bytes)

    assert schedule.meta.history_prefix_hash
    assert schedule.meta.fixed_events_hash
    assert schedule.meta.control_events_hash
    assert len({
        schedule.meta.history_prefix_hash,
        schedule.meta.fixed_events_hash,
        schedule.meta.control_events_hash,
    }) == 3
    assert rebuilt.meta == schedule.meta
    assert hash_schedule(rebuilt) == hash_schedule(schedule)
    assert schedule_hash_parts(rebuilt) == schedule_hash_parts(schedule)
    assert len(schedule_hash_parts(schedule)) == 64


def test_initial_state_matches_december_2006_slice(schedule) -> None:
    available = [
        well
        for well, state in schedule.initial_state.items()
        if state.availability is Availability.AVAILABLE
    ]
    producers = [
        well for well in available if schedule.initial_state[well].role is Role.PROD
    ]
    injectors = [
        well for well in available if schedule.initial_state[well].role is Role.INJ
    ]

    assert len(producers) == 58
    assert len(injectors) == 23
    assert sum(schedule.initial_state[well].setpoint for well in producers) == 1505.0
    assert sum(schedule.initial_state[well].setpoint for well in injectors) == 1495.0


def test_well_state_has_four_fields(schedule) -> None:
    state = next(iter(schedule.initial_state.values()))

    assert set(WellState.__dataclass_fields__) == {
        "availability",
        "role",
        "operating_status",
        "setpoint",
    }
    assert isinstance(state.setpoint, float)


def test_load_schedule_reads_real_deck() -> None:
    schedule = load_schedule(MODEL_Z_SCHEDULE, provenance="базовый дек")

    assert schedule.meta.provenance == "базовый дек"
    assert schedule.control_events
    assert schedule.fixed_deck_events


def test_deck_without_welspecs_is_rejected() -> None:
    with pytest.raises(ScheduleBuildError, match="WELSPECS"):
        deck_well_axis(b"DATES\n 01 JAN 2007 /\n/\n")
