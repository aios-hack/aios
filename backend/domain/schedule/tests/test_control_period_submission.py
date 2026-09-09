from __future__ import annotations

from collections import Counter

import pytest

from backend.core.contracts import (
    N_CONTROL_DATES,
    N_INTERVALS,
    T0,
    Availability,
    Schedule,
    ScheduleMeta,
    hash_schedule,
)
from backend.domain.schedule import build_schedule, parse_schedule
from backend.domain.schedule.emit import verify_schedule_round_trip
from backend.infrastructure.opm import (
    OpmDeckEmitter,
    render_control_period_include,
    render_schedule_include,
)

from conftest import missing_reason, model_z_dir

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


def test_the_source_deck_really_carries_a_historical_part() -> None:
    source = (MODEL_Z / "Model_Z_sch.inc").read_bytes()
    parsed = parse_schedule(source)

    historical = [
        block
        for block in parsed.blocks
        if block.event_date is not None and block.event_date < T0
    ]

    assert len(parsed.dates) == N_CONTROL_DATES + parsed.t0_deck_date_index
    assert parsed.t0_deck_date_index == 146
    assert Counter(block.keyword for block in historical)["DATES"] == 146


def test_the_submitted_file_carries_no_historical_date(plan: Schedule) -> None:
    submitted = render_control_period_include(plan, MODEL_Z)
    parsed = parse_schedule(submitted.raw)

    before_t0 = [date for date in parsed.dates if date < T0]

    assert len(before_t0) == 1
    assert parsed.t0_deck_date_index == 1
    assert parsed.dates[1] == T0
    assert parsed.dates[-1] == parse_schedule(
        render_schedule_include(plan, MODEL_Z).raw
    ).dates[-1]


def test_the_single_pre_t0_block_is_the_state_at_t0_not_history(
    plan: Schedule,
) -> None:
    submitted = render_control_period_include(plan, MODEL_Z)
    parsed = parse_schedule(submitted.raw)

    pre_t0 = [
        block
        for block in parsed.blocks
        if block.event_date is not None and block.event_date < T0
    ]

    assert [block.keyword for block in pre_t0] == ["DATES", "WCONPROD", "WCONINJE"]
    assert all(block.control_step is None for block in pre_t0)
    commissioned = sum(
        1
        for state in plan.initial_state.values()
        if state.availability is Availability.AVAILABLE
    )
    seeded = sum(
        len(block.raw.splitlines()) - 2 for block in pre_t0 if block.keyword != "DATES"
    )
    assert seeded == commissioned


def test_every_emitted_event_belongs_to_the_managed_period(plan: Schedule) -> None:
    submitted = render_control_period_include(plan, MODEL_Z)
    parsed = parse_schedule(submitted.raw)

    assert parsed.control_events
    assert all(
        0 <= event.control_step < N_INTERVALS for event in parsed.control_events
    )
    assert all(
        0 <= event.control_step < N_INTERVALS for event in parsed.fixed_deck_events
    )


def test_the_number_of_control_blocks_matches_the_managed_period(
    plan: Schedule,
) -> None:
    submitted = render_control_period_include(plan, MODEL_Z)
    parsed = parse_schedule(submitted.raw)

    dates = [block for block in parsed.blocks if block.keyword == "DATES"]
    managed = [block for block in dates if block.control_step is not None]

    assert len(managed) == N_CONTROL_DATES
    assert {block.control_step for block in managed} == set(range(N_CONTROL_DATES))
    assert len(dates) == N_CONTROL_DATES + 1


def test_the_managed_period_file_drops_the_history_the_full_deck_keeps(
    plan: Schedule,
) -> None:
    full = render_schedule_include(plan, MODEL_Z)
    submitted = render_control_period_include(plan, MODEL_Z)

    full_dates = parse_schedule(full.raw).dates
    submitted_dates = parse_schedule(submitted.raw).dates

    assert len(full_dates) == N_CONTROL_DATES + 146
    assert len(submitted_dates) == N_CONTROL_DATES + 1
    assert submitted_dates[1:] == full_dates[146:]
    assert len(submitted.raw) < len(full.raw)


def test_the_round_trip_still_holds_on_our_plan(plan: Schedule) -> None:
    submitted = render_control_period_include(plan, MODEL_Z)

    report = verify_schedule_round_trip(plan, submitted.raw)

    assert report.ok, report.format()
    assert report.divergence is None
    assert report.source_hash == report.reparsed_hash == hash_schedule(plan)
    report.raise_if_broken()


def test_the_managed_period_preserves_both_event_layers(plan: Schedule) -> None:
    full = render_schedule_include(plan, MODEL_Z)
    submitted = render_control_period_include(plan, MODEL_Z)

    from_full = parse_schedule(full.raw)
    from_submitted = parse_schedule(submitted.raw)

    assert from_submitted.control_events == from_full.control_events
    assert from_submitted.fixed_deck_events == from_full.fixed_deck_events


def test_the_submitted_file_rebuilds_the_same_schedule(plan: Schedule) -> None:
    submitted = render_control_period_include(plan, MODEL_Z)

    rebuilt = build_schedule(
        parse_schedule(submitted.raw), submitted.raw, provenance="Model_Z"
    )

    assert rebuilt.initial_state == plan.initial_state
    assert rebuilt.control_events == plan.control_events
    assert rebuilt.fixed_deck_events == plan.fixed_deck_events
    assert hash_schedule(rebuilt) == hash_schedule(plan)


def test_rendering_the_managed_period_is_deterministic(plan: Schedule) -> None:
    first = render_control_period_include(plan, MODEL_Z)
    second = render_control_period_include(plan, str(MODEL_Z))

    assert first.raw == second.raw
    assert first.content_hash == second.content_hash


def test_a_missing_model_dir_is_reported(plan: Schedule, tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        render_control_period_include(plan, tmp_path)
