from __future__ import annotations

import pytest

from backend.core.contracts import MAX_LRAT_M3_PER_DAY, EventKind, Rule

from backend.domain.policy import RuleContext, RuleFlags, apply_rule, make_theta
from backend.domain.policy.rules import r2
from backend.domain.policy.tests.conftest import producer, state_of


def test_r2_has_two_theta_parameters() -> None:
    assert r2.THETA_NAMES == ("r2_watercut_pivot", "r2_gain")


def test_clean_well_is_pushed_up_dirty_is_choked(context: RuleContext) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=50.0, watercut=0.30, setpoint=50.0),
        producer("43", liquid_rate_m3_per_day=50.0, watercut=0.98, setpoint=50.0),
    )
    theta = make_theta({"r2_watercut_pivot": 0.9, "r2_gain": 0.5})
    outcome = apply_rule(Rule.R2, state, context, theta, RuleFlags())
    targets = {event.well: event.value for event in outcome.decisions}
    assert targets["42"] > 50.0
    assert targets["43"] < 50.0


def test_pivot_watercut_leaves_rate_unchanged(context: RuleContext) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=50.0, watercut=0.9, setpoint=10.0)
    )
    theta = make_theta({"r2_watercut_pivot": 0.9, "r2_gain": 0.7})
    outcome = apply_rule(Rule.R2, state, context, theta, RuleFlags())
    assert outcome.decisions[0].value == pytest.approx(50.0)


def test_zero_gain_reproduces_current_rate(context: RuleContext) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=37.0, watercut=0.42, setpoint=10.0)
    )
    theta = make_theta({"r2_gain": 0.0})
    outcome = apply_rule(Rule.R2, state, context, theta, RuleFlags())
    assert outcome.decisions[0].value == pytest.approx(37.0)


def test_target_never_exceeds_methodology_ceiling(context: RuleContext) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=480.0, watercut=0.0, setpoint=480.0)
    )
    theta = make_theta({"r2_watercut_pivot": 0.5, "r2_gain": 1.0})
    outcome = apply_rule(Rule.R2, state, context, theta, RuleFlags())
    assert outcome.decisions[0].value <= MAX_LRAT_M3_PER_DAY


def test_decisions_are_set_lrat(context: RuleContext) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=50.0, watercut=0.30, setpoint=50.0)
    )
    outcome = apply_rule(Rule.R2, state, context, make_theta({}), RuleFlags())
    assert {event.kind for event in outcome.decisions} == {EventKind.SET_LRAT}


def test_trace_carries_decision_numbers(context: RuleContext) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=50.0, watercut=0.30, setpoint=50.0)
    )
    theta = make_theta({"r2_watercut_pivot": 0.9, "r2_gain": 0.5})
    outcome = apply_rule(Rule.R2, state, context, theta, RuleFlags())
    entry = outcome.trace[0]
    assert entry.rule is Rule.R2
    assert entry.decision == "SET_LRAT"
    assert entry.inputs["theta_r2_watercut_pivot"] == 0.9
    assert entry.inputs["theta_r2_gain"] == 0.5
    assert entry.inputs["watercut"] == pytest.approx(0.30)
    assert entry.inputs["target_rate_m3_per_day"] > 0.0


def test_shut_well_is_not_touched(context: RuleContext) -> None:
    state = state_of(
        producer(
            "42",
            liquid_rate_m3_per_day=50.0,
            watercut=0.30,
            setpoint=50.0,
            is_open=False,
        )
    )
    outcome = apply_rule(Rule.R2, state, context, make_theta({}), RuleFlags())
    assert outcome.decisions == ()


def test_theta_outside_bounds_rejected(context: RuleContext) -> None:
    with pytest.raises(ValueError):
        make_theta({"r2_gain": 1.5})
