import hashlib
import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from contracts import (
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from schedule import (
    ScheduleCanonicalError,
    build_schedule,
    canonical_bytes,
    canonical_digest,
    canonical_hash_parts,
    canonicalize,
    canonicalize_control_events,
    canonicalize_fixed_events,
    ecmascript_number,
    hash_canonical_schedule,
    hash_parts_raw,
    load_schedule,
    normalize_well_state,
    parse_schedule,
)


MODEL_Z_SCHEDULE = (
    Path(__file__).resolve().parents[3] / "docs" / "models" / "Model_Z" / "Model_Z_sch.inc"
)


@pytest.fixture(scope="module")
def deck_bytes() -> bytes:
    return MODEL_Z_SCHEDULE.read_bytes()


@pytest.fixture(scope="module")
def schedule(deck_bytes: bytes) -> Schedule:
    return build_schedule(parse_schedule(deck_bytes), deck_bytes)


def _available(setpoint: float) -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.OPEN,
        setpoint=setpoint,
    )


def _schedule_from(
    initial_state: dict[str, WellState],
    fixed: list[FixedDeckEvent],
    control: list[ControlEvent],
) -> Schedule:
    meta = ScheduleMeta(wells=tuple(sorted(initial_state, key=lambda well: int(well))))
    return Schedule(
        meta=meta,
        initial_state=initial_state,
        fixed_deck_events=tuple(fixed),
        control_events=tuple(control),
    )


def _sample() -> Schedule:
    return _schedule_from(
        {
            "1": _available(45.0),
            "2": WellState(
                availability=Availability.AVAILABLE,
                role=Role.INJ,
                operating_status=OperatingStatus.OPEN,
                setpoint=60.0,
            ),
            "3": WellState(
                availability=Availability.NOT_COMMISSIONED,
                role=Role.NONE,
                operating_status=OperatingStatus.SHUT,
                setpoint=0.0,
            ),
        },
        [
            FixedDeckEvent(control_step=2, well="3", operator="COMPDAT", raw_args=("1", "1")),
            FixedDeckEvent(control_step=0, well="1", operator="WPIMULT", raw_args=("0.5",)),
        ],
        [
            ControlEvent(control_step=1, well="2", kind=EventKind.SET_RATE, value=60.0),
            ControlEvent(control_step=0, well="1", kind=EventKind.SET_LRAT, value=45.0),
            ControlEvent(control_step=1, well="2", kind=EventKind.CONVERT_INJ),
            ControlEvent(control_step=0, well="1", kind=EventKind.OPEN),
        ],
    )


def test_ecmascript_number_matches_javascript_rules() -> None:
    assert ecmascript_number(1.0) == "1"
    assert ecmascript_number(1) == "1"
    assert ecmascript_number(45.0) == "45"
    assert ecmascript_number(0.1) == "0.1"
    assert ecmascript_number(1.5) == "1.5"
    assert ecmascript_number(-0.0) == "0"
    assert ecmascript_number(0.0) == "0"
    assert ecmascript_number(1e21) == "1e+21"
    assert ecmascript_number(1e-7) == "1e-7"
    assert ecmascript_number(1e-6) == "0.000001"
    assert ecmascript_number(1e20) == "100000000000000000000"
    assert ecmascript_number(-45.5) == "-45.5"
    assert ecmascript_number(1234567890123456789012.0) == "1.2345678901234568e+21"


def test_ecmascript_number_rejects_nan_and_infinity() -> None:
    with pytest.raises(ScheduleCanonicalError):
        ecmascript_number(float("nan"))
    with pytest.raises(ScheduleCanonicalError):
        ecmascript_number(float("inf"))


def test_canonical_bytes_is_jcs_not_python_json() -> None:
    raw = canonical_bytes({"value": 1.0, "count": 1})

    assert raw == b'{"count":1,"value":1}'
    assert b"1.0" not in raw
    assert json.dumps({"value": 1.0}).encode() != canonical_bytes({"value": 1.0})


def test_canonical_bytes_sorts_keys_and_drops_whitespace() -> None:
    raw = canonical_bytes({"b": 1, "a": {"z": 2, "y": 3}})

    assert raw == b'{"a":{"y":3,"z":2},"b":1}'
    assert b" " not in raw
    assert b"\n" not in raw
    assert raw.decode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf")


def test_canonical_bytes_serializes_dates_as_iso() -> None:
    schedule = canonicalize(_sample())

    assert b'"t0":"2007-01-01"' in canonical_bytes(schedule.meta)


def test_canonical_bytes_is_key_order_independent() -> None:
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})


def test_shuffled_input_gives_the_same_hash(schedule: Schedule) -> None:
    rng = random.Random(20260816)
    control = list(schedule.control_events)
    fixed = list(schedule.fixed_deck_events)
    rng.shuffle(control)

    shuffled = _schedule_from(dict(schedule.initial_state), fixed, control)
    shuffled = replace(
        shuffled,
        meta=replace(shuffled.meta, wells=schedule.meta.wells),
    )

    assert hash_canonical_schedule(shuffled) == hash_canonical_schedule(schedule)
    assert canonicalize(shuffled).control_events == schedule.control_events


def test_canonicalize_is_idempotent(schedule: Schedule) -> None:
    once = canonicalize(schedule)
    twice = canonicalize(once)

    assert twice == once
    assert canonical_bytes(twice.control_events) == canonical_bytes(once.control_events)
    assert hash_canonical_schedule(twice) == hash_canonical_schedule(once)


def test_hash_is_sixty_four_hex_chars(schedule: Schedule) -> None:
    digest = hash_canonical_schedule(schedule)

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_hash_concatenates_raw_digests_not_hex_strings() -> None:
    schedule = canonicalize(_sample())
    parts = (
        canonical_digest(schedule.initial_state),
        canonical_digest(list(schedule.fixed_deck_events)),
        canonical_digest(list(schedule.control_events)),
    )
    raw_concat = hashlib.sha256(b"".join(parts)).hexdigest()
    hex_concat = hashlib.sha256(
        "".join(part.hex() for part in parts).encode("utf-8")
    ).hexdigest()

    assert all(len(part) == 32 for part in parts)
    assert hash_canonical_schedule(schedule) == raw_concat
    assert hash_canonical_schedule(schedule) != hex_concat


def test_hash_matches_explicit_three_part_formula() -> None:
    schedule = canonicalize(_sample())

    assert hash_canonical_schedule(schedule) == hash_parts_raw(
        schedule.initial_state, schedule.fixed_deck_events, schedule.control_events
    )


def test_history_part_change_changes_hash() -> None:
    base = _sample()
    changed_state = dict(base.initial_state)
    changed_state["1"] = _available(46.0)
    changed = _schedule_from(changed_state, list(base.fixed_deck_events), list(base.control_events))

    assert hash_canonical_schedule(changed) != hash_canonical_schedule(base)
    assert canonical_hash_parts(changed)[0] != canonical_hash_parts(base)[0]


def test_fixed_layer_change_changes_hash() -> None:
    base = _sample()
    without_perforation = [
        event for event in base.fixed_deck_events if event.operator != "COMPDAT"
    ]
    changed = _schedule_from(
        dict(base.initial_state), without_perforation, list(base.control_events)
    )

    assert hash_canonical_schedule(changed) != hash_canonical_schedule(base)
    assert canonical_hash_parts(changed)[1] != canonical_hash_parts(base)[1]
    assert canonical_hash_parts(changed)[2] == canonical_hash_parts(base)[2]


def test_control_layer_change_changes_hash() -> None:
    base = _sample()
    control = list(base.control_events)
    control.append(ControlEvent(control_step=5, well="1", kind=EventKind.SHUT))
    changed = _schedule_from(dict(base.initial_state), list(base.fixed_deck_events), control)

    assert hash_canonical_schedule(changed) != hash_canonical_schedule(base)
    assert canonical_hash_parts(changed)[2] != canonical_hash_parts(base)[2]
    assert canonical_hash_parts(changed)[1] == canonical_hash_parts(base)[1]


def test_semantic_order_inside_step_is_fixed_then_convert_then_mode_then_status() -> None:
    events = [
        ControlEvent(control_step=4, well="9", kind=EventKind.SHUT),
        ControlEvent(control_step=4, well="9", kind=EventKind.SET_RATE, value=12.0),
        ControlEvent(control_step=4, well="9", kind=EventKind.CONVERT_INJ),
    ]

    ordered = canonicalize_control_events(events)

    assert [event.kind for event in ordered] == [
        EventKind.CONVERT_INJ,
        EventKind.SET_RATE,
        EventKind.SHUT,
    ]


def test_fixed_events_keep_deck_order_inside_step() -> None:
    first = FixedDeckEvent(control_step=3, well="9", operator="COMPDAT", raw_args=("b",))
    second = FixedDeckEvent(control_step=3, well="1", operator="COMPDAT", raw_args=("a",))
    earlier = FixedDeckEvent(control_step=1, well="5", operator="WPIMULT", raw_args=("0.5",))

    ordered = canonicalize_fixed_events([first, second, earlier])

    assert ordered == (earlier, first, second)


def test_exact_duplicates_are_dropped_conflicts_are_rejected() -> None:
    event = ControlEvent(control_step=0, well="7", kind=EventKind.SET_LRAT, value=30.0)

    assert canonicalize_control_events([event, event]) == (event,)

    with pytest.raises(ScheduleCanonicalError, match="конфликтующие"):
        canonicalize_control_events(
            [event, ControlEvent(control_step=0, well="7", kind=EventKind.SET_LRAT, value=31.0)]
        )


def test_not_commissioned_state_is_normalized() -> None:
    state = WellState(
        availability=Availability.NOT_COMMISSIONED,
        role=Role.NONE,
        operating_status=OperatingStatus.SHUT,
        setpoint=0.0,
    )

    assert normalize_well_state(state) == state


def test_negative_zero_setpoint_normalizes_to_zero_bytes() -> None:
    positive = _available(0.0)
    negative = _available(-0.0)

    assert canonical_bytes(normalize_well_state(negative)) == canonical_bytes(
        normalize_well_state(positive)
    )
    assert b'"setpoint":0' in canonical_bytes(normalize_well_state(negative))


def test_initial_state_outside_axis_is_rejected() -> None:
    base = _sample()
    broken = replace(base, meta=replace(base.meta, wells=("1", "2")))

    with pytest.raises(ScheduleCanonicalError, match="вне оси"):
        canonicalize(broken)


def test_real_deck_hash_is_stable_between_independent_builds(deck_bytes: bytes) -> None:
    first = build_schedule(parse_schedule(deck_bytes), deck_bytes)
    second = load_schedule(MODEL_Z_SCHEDULE)

    assert hash_canonical_schedule(first) == hash_canonical_schedule(second)
    assert canonical_hash_parts(first) == canonical_hash_parts(second)
    assert len(hash_canonical_schedule(first)) == 64


def test_real_deck_meta_hashes_are_the_three_parts(schedule: Schedule) -> None:
    parts = canonical_hash_parts(schedule)

    assert parts == (
        schedule.meta.history_prefix_hash,
        schedule.meta.fixed_events_hash,
        schedule.meta.control_events_hash,
    )
    assert len(set(parts)) == 3
    assert all(len(part) == 64 for part in parts)


def test_real_deck_setpoints_serialize_without_python_float_suffix(schedule: Schedule) -> None:
    raw = canonical_bytes(list(schedule.control_events))

    assert b'"value":45,' in raw
    assert b'"value":45.0,' not in raw
