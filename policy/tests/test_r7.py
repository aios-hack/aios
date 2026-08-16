from __future__ import annotations

from dataclasses import replace

import pytest

from contracts import EventKind, Rule
from contracts.policy import MAX_THETA_PARAMS

from policy import (
    ADMISSION_CRITERIA,
    DEFAULT_RULE_FLAGS,
    IMPLEMENTED_RULES,
    RuleContext,
    RuleFlags,
    WellMemory,
    apply_all,
    apply_rule,
    budget_free,
    budget_used,
    default_theta,
    make_theta,
    specs_for,
)
from policy.rules import r7
from policy.tests.conftest import (
    DECIDING_WELLS,
    deciding_context,
    memory_of,
    producer,
    state_of,
)

ON = RuleFlags().with_enabled(Rule.R7)


def uplift_context(context: RuleContext, **by_well: float) -> RuleContext:
    return replace(context, cyclic_uplift_rub_per_well=dict(by_well))


def test_r7_is_off_by_default() -> None:
    assert DEFAULT_RULE_FLAGS[Rule.R7] is False
    assert Rule.R7 in IMPLEMENTED_RULES


def test_r7_off_by_default_makes_no_decisions_and_no_trace(
    context: RuleContext,
) -> None:
    state = state_of(producer("42", liquid_rate_m3_per_day=30.0, watercut=0.98))
    ctx = uplift_context(context, **{"42": 500_000_000.0})
    outcome = apply_rule(Rule.R7, state, ctx, default_theta(), RuleFlags())
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_r7_absent_from_a_default_combined_run(context: RuleContext) -> None:
    state = state_of(*DECIDING_WELLS, control_step=3)
    ctx = replace(
        deciding_context(context),
        cyclic_uplift_rub_per_well={"42": 500_000_000.0},
    )
    outcome = apply_all(state, ctx, default_theta(), RuleFlags())
    assert Rule.R7 not in {entry.rule for entry in outcome.trace}
    with_r7 = apply_all(state, ctx, default_theta(), ON)
    assert Rule.R7 in {entry.rule for entry in with_r7.trace}


def test_r7_fits_the_two_reserved_theta_slots() -> None:
    assert len(specs_for(Rule.R7)) == 2
    assert budget_used() == MAX_THETA_PARAMS
    assert budget_free() == 0


def test_r7_theta_names_are_declared() -> None:
    assert r7.THETA_NAMES == ("r7_cycle_months", "r7_watercut_floor")
    for name in r7.THETA_NAMES:
        assert name in default_theta().values


def test_admission_criterion_is_one_field_phrase() -> None:
    criterion = ADMISSION_CRITERIA[Rule.R7]
    assert criterion.endswith(".")
    assert len(criterion.split()) <= 20


def test_without_measured_uplift_the_rule_never_cycles(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=30.0, watercut=0.98),
        control_step=3,
    )
    outcome = apply_rule(Rule.R7, state, context, default_theta(), ON)
    assert outcome.decisions == ()
    assert [entry.decision for entry in outcome.trace] == [
        "NO_CYCLE_UPLIFT_NOT_MEASURED"
    ]


def test_uplift_below_two_event_costs_does_not_justify_a_cycle(
    context: RuleContext,
) -> None:
    cost = context.normatives.event_cost_rub
    state = state_of(
        producer("42", liquid_rate_m3_per_day=30.0, watercut=0.99),
        control_step=3,
    )
    ctx = uplift_context(context, **{"42": 2.0 * cost - 1.0})
    outcome = apply_rule(Rule.R7, state, ctx, default_theta(), ON)
    assert outcome.decisions == ()
    entry = outcome.trace[0]
    assert entry.decision == "NO_CYCLE_UPLIFT_NOT_MEASURED"
    assert entry.inputs["cycle_cost_rub"] == 2.0 * cost


def test_a_cycle_costs_two_events(context: RuleContext) -> None:
    cost = context.normatives.event_cost_rub
    assert r7.cycle_cost_rub(cost) == 2.0 * cost


def test_twenty_cycles_on_a_well_cost_forty_event_costs(
    context: RuleContext,
) -> None:
    cost = context.normatives.event_cost_rub
    assert 20 * r7.cycle_cost_rub(cost) == 40.0 * cost


def test_uplift_above_cost_and_foregone_margin_shuts_in_the_rest_phase(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=30.0, watercut=0.98),
        control_step=3,
    )
    ctx = uplift_context(context, **{"42": 500_000_000.0})
    outcome = apply_rule(Rule.R7, state, ctx, default_theta(), ON)
    assert r7.is_rest_phase(3, 3.0)
    assert [event.kind for event in outcome.decisions] == [EventKind.SHUT]
    assert outcome.trace[0].decision == "CYCLE_SHUT"


def test_the_well_reopens_in_the_work_phase(context: RuleContext) -> None:
    state = state_of(
        producer(
            "42", liquid_rate_m3_per_day=30.0, watercut=0.98, is_open=False
        ),
        control_step=6,
    )
    ctx = uplift_context(context, **{"42": 500_000_000.0})
    outcome = apply_rule(Rule.R7, state, ctx, default_theta(), ON)
    assert not r7.is_rest_phase(6, 3.0)
    assert [event.kind for event in outcome.decisions] == [EventKind.OPEN]
    assert outcome.trace[0].decision == "CYCLE_OPEN"


def test_phase_alternates_with_the_declared_period() -> None:
    period = 3.0
    phases = [r7.is_rest_phase(step, period) for step in range(12)]
    assert phases == [False] * 3 + [True] * 3 + [False] * 3 + [True] * 3


def test_a_shorter_period_cycles_more_often() -> None:
    assert [r7.is_rest_phase(step, 1.0) for step in range(4)] == [
        False,
        True,
        False,
        True,
    ]


def test_non_positive_period_is_rejected() -> None:
    with pytest.raises(ValueError):
        r7.is_rest_phase(0, 0.0)


def test_clean_wells_below_the_floor_are_never_cycled(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("43", liquid_rate_m3_per_day=40.0, watercut=0.40),
        control_step=3,
    )
    ctx = uplift_context(context, **{"43": 500_000_000.0})
    outcome = apply_rule(Rule.R7, state, ctx, default_theta(), ON)
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_the_watercut_floor_is_the_boundary(context: RuleContext) -> None:
    theta = make_theta({"r7_watercut_floor": 0.95})
    ctx = uplift_context(context, **{"42": 500_000_000.0})
    below = state_of(
        producer("42", liquid_rate_m3_per_day=30.0, watercut=0.94),
        control_step=3,
    )
    above = state_of(
        producer("42", liquid_rate_m3_per_day=30.0, watercut=0.96),
        control_step=3,
    )
    assert apply_rule(Rule.R7, below, ctx, theta, ON).trace == ()
    assert apply_rule(Rule.R7, above, ctx, theta, ON).trace != ()


def test_foregone_margin_of_a_loss_making_well_is_not_a_benefit(
    context: RuleContext,
) -> None:
    foregone = r7.foregone_margin_rub(
        context.normatives,
        context.oil_density_t_per_m3,
        liquid_rate_m3_per_day=1.0,
        watercut=0.999,
        cycle_months=3.0,
    )
    assert foregone == 0.0


def test_trace_carries_every_number_the_decision_used(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=30.0, watercut=0.98),
        control_step=3,
    )
    ctx = uplift_context(context, **{"42": 500_000_000.0})
    outcome = apply_rule(Rule.R7, state, ctx, default_theta(), ON)
    inputs = outcome.trace[0].inputs
    for name in (
        "liquid_rate_m3_per_day",
        "watercut",
        "theta_r7_cycle_months",
        "theta_r7_watercut_floor",
        "event_cost_rub",
        "cycle_cost_rub",
        "foregone_margin_rub",
        "measured_cyclic_uplift_rub",
        "in_rest_phase",
    ):
        assert name in inputs


def test_the_rule_is_deterministic(context: RuleContext) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=30.0, watercut=0.98),
        producer("44", liquid_rate_m3_per_day=20.0, watercut=0.97),
        control_step=3,
    )
    ctx = uplift_context(
        context, **{"42": 500_000_000.0, "44": 500_000_000.0}
    )
    first = apply_rule(Rule.R7, state, ctx, default_theta(), ON)
    second = apply_rule(Rule.R7, state, ctx, default_theta(), ON)
    assert first == second


def test_a_converted_well_is_no_longer_cycled(context: RuleContext) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=30.0, watercut=0.98),
        control_step=3,
    )
    ctx = replace(
        uplift_context(context, **{"42": 500_000_000.0}),
        memory=memory_of(**{"42": WellMemory(converted_to_injection=True)}),
    )
    assert apply_rule(Rule.R7, state, ctx, default_theta(), ON).trace == ()


def test_the_benefit_is_declared_unconfirmed() -> None:
    assert "не подтверждена" in r7.BENEFIT_UNCONFIRMED
