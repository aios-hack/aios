from __future__ import annotations

import pytest

from backend.contexts.schedule.domain.schedule import N_CONTROL_DATES, T0
from backend.shared.hashing import hash_schedule
from backend.contexts.schedule.domain.build import build_schedule
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.schedule.application.emit import verify_schedule_round_trip
from backend.contexts.reservoir.infrastructure.opm_deck import (
    render_control_period_include,
    render_schedule_include,
    render_submission_history,
)
from tests.support.backend.environment import model_z_dir, missing_reason

MODEL_Z = model_z_dir()
pytestmark = pytest.mark.skipif(MODEL_Z is None, reason=missing_reason("Model_Z"))


@pytest.fixture(scope="module")
def plan():
    raw = (MODEL_Z / "Model_Z_sch.inc").read_bytes()
    baseline = build_schedule(parse_schedule(raw), raw)
    rendered = render_schedule_include(baseline, MODEL_Z)
    return build_schedule(parse_schedule(rendered.raw), rendered.raw)


def test_submission_contains_exactly_the_managed_dates_and_no_preamble(plan):
    raw = render_control_period_include(plan, MODEL_Z).raw
    parsed = parse_schedule(raw)
    assert len(parsed.dates) == N_CONTROL_DATES
    assert parsed.dates[0] == T0
    assert all(d >= T0 for d in parsed.dates)
    assert b"WELSPECS" not in raw
    assert parsed.t0_deck_date_index == 0


def test_submitted_bytes_plus_organizer_history_equal_the_verified_include(plan):
    raw = render_control_period_include(plan, MODEL_Z).raw
    history = render_submission_history(plan, MODEL_Z)
    assert history + raw == render_schedule_include(plan, MODEL_Z).raw
    report = verify_schedule_round_trip(plan, raw, history_prefix=history)
    assert report.ok, report.format()
    assert report.source_hash == report.reparsed_hash == hash_schedule(plan)


def test_both_event_layers_and_initial_state_survive_in_context(plan):
    raw = render_submission_history(plan, MODEL_Z) + render_control_period_include(plan, MODEL_Z).raw
    rebuilt = build_schedule(parse_schedule(raw), raw)
    assert rebuilt.initial_state == plan.initial_state
    assert rebuilt.control_events == plan.control_events
    assert rebuilt.fixed_deck_events == plan.fixed_deck_events


def test_export_is_deterministic_and_smaller_than_full_deck(plan):
    a = render_control_period_include(plan, MODEL_Z)
    b = render_control_period_include(plan, str(MODEL_Z))
    assert a.raw == b.raw and a.content_hash == b.content_hash
    assert len(a.raw) < len(render_schedule_include(plan, MODEL_Z).raw)


def test_missing_model_is_reported(plan, tmp_path):
    with pytest.raises(FileNotFoundError):
        render_control_period_include(plan, tmp_path)
