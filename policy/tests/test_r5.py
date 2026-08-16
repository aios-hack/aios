from __future__ import annotations

from dataclasses import replace

import pytest

from contracts import EventKind, Rule

from policy import RuleContext, RuleFlags, apply_rule, default_theta, make_theta
from policy.rules import r5
from policy.tests.conftest import groups_of, injector, producer, state_of

GROUP = "G1"
WELLS = (
    producer("42", liquid_rate_m3_per_day=40.0, watercut=0.5, setpoint=40.0),
    producer("43", liquid_rate_m3_per_day=60.0, watercut=0.5, setpoint=60.0),
    injector("101", injection_rate_m3_per_day=60.0),
    injector("102", injection_rate_m3_per_day=40.0),
)
OFFTAKE = 100.0


def context_with(context: RuleContext, injection: float) -> RuleContext:
    return replace(
        context,
        groups=groups_of({GROUP: ("42", "43", "101", "102")}),
        group_injection_m3_per_day={GROUP: injection},
        group_offtake_m3_per_day={GROUP: OFFTAKE},
    )


def outcome_of(context: RuleContext, injection: float, theta=None):
    return r5.apply(
        state_of(*WELLS),
        context_with(context, injection),
        theta if theta is not None else default_theta(),
    )


def test_rule_states_its_criterion_in_field_language() -> None:
    assert r5.ADMISSION_CRITERION.endswith(".")
    assert len(r5.ADMISSION_CRITERION.split()) <= 20


def test_r5_spends_two_theta() -> None:
    assert r5.THETA_NAMES == ("r5_compensation_low", "r5_compensation_high")


def test_compensation_inside_the_corridor_is_left_alone(
    context: RuleContext,
) -> None:
    outcome = outcome_of(context, injection=100.0)
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_compensation_below_the_corridor_is_raised_to_the_lower_bound(
    context: RuleContext,
) -> None:
    outcome = outcome_of(context, injection=50.0)
    low = default_theta().values["r5_compensation_low"]
    total = sum(d.value for d in outcome.decisions)
    assert total == pytest.approx(OFFTAKE * low)
    assert all(d.kind is EventKind.SET_RATE for d in outcome.decisions)


def test_compensation_above_the_corridor_is_lowered_to_the_upper_bound(
    context: RuleContext,
) -> None:
    outcome = outcome_of(context, injection=180.0)
    high = default_theta().values["r5_compensation_high"]
    total = sum(d.value for d in outcome.decisions)
    assert total == pytest.approx(OFFTAKE * high)


def test_the_correction_is_split_by_the_current_share_of_each_injector(
    context: RuleContext,
) -> None:
    outcome = outcome_of(context, injection=50.0)
    by_well = {d.well: d.value for d in outcome.decisions}
    assert by_well["101"] > by_well["102"]
    assert by_well["101"] / by_well["102"] == pytest.approx(60.0 / 40.0)


def test_the_trace_carries_the_compensation_before_and_after(
    context: RuleContext,
) -> None:
    outcome = outcome_of(context, injection=50.0)
    low = default_theta().values["r5_compensation_low"]
    for entry in outcome.trace:
        assert entry.inputs["compensation"] == pytest.approx(0.5)
        assert entry.inputs["target_compensation"] == pytest.approx(low)
        assert entry.inputs["group_offtake_m3_per_day"] == OFFTAKE


def test_a_wider_corridor_leaves_more_states_untouched(
    context: RuleContext,
) -> None:
    narrow = make_theta(
        {"r5_compensation_low": 0.98, "r5_compensation_high": 1.02}
    )
    wide = make_theta(
        {"r5_compensation_low": 0.5, "r5_compensation_high": 1.6}
    )
    assert outcome_of(context, injection=120.0, theta=narrow).decisions != ()
    assert outcome_of(context, injection=120.0, theta=wide).decisions == ()


def test_compensation_is_a_group_quantity_not_a_well_one(
    context: RuleContext,
) -> None:
    with pytest.raises(ValueError, match="нарезку на участки"):
        r5.apply(state_of(*WELLS), context, default_theta())


def test_missing_group_offtake_is_refused(context: RuleContext) -> None:
    broken = replace(
        context,
        groups=groups_of({GROUP: ("42", "101")}),
        group_injection_m3_per_day={GROUP: 100.0},
        group_offtake_m3_per_day={},
    )
    with pytest.raises(ValueError, match="коридор"):
        r5.apply(state_of(*WELLS), broken, default_theta())


def test_compensation_at_zero_offtake_is_not_defined() -> None:
    with pytest.raises(ValueError, match="нулевом отборе"):
        r5.compensation(100.0, 0.0)


def test_disabled_r5_makes_no_decisions_and_no_records(
    context: RuleContext,
) -> None:
    off = apply_rule(
        Rule.R5,
        state_of(*WELLS),
        context_with(context, 50.0),
        default_theta(),
        RuleFlags().with_disabled(Rule.R5),
    )
    assert off.decisions == ()
    assert off.trace == ()
