from __future__ import annotations

from dataclasses import replace

import pytest

from contracts import ControlEvent, EventKind, Rule

from policy import (
    RuleContext,
    RuleFlags,
    RuleOutcome,
    WellMemory,
    annual_margin_rub,
    apply_rule,
    default_theta,
    make_theta,
)
from policy.rules import r0, r3
from policy.tests.conftest import memory_of, producer, state_of

AT_THRESHOLD_WATERCUT = 0.968955
CLEARLY_LOSING_WATERCUT = 0.995
CLEARLY_PROFITABLE_WATERCUT = 0.60
RATE = 20.0


def wobbling(step: int) -> float:
    return AT_THRESHOLD_WATERCUT + (0.004 if step % 2 else -0.004)


def outcome_of(context: RuleContext, wells, theta=None, memory=None):
    ctx = replace(context, memory=memory if memory is not None else memory_of())
    return r3.apply(
        state_of(*wells),
        ctx,
        theta if theta is not None else default_theta(),
    )


def test_rule_states_its_criterion_in_field_language() -> None:
    assert r3.ADMISSION_CRITERION.endswith(".")
    assert len(r3.ADMISSION_CRITERION.split()) <= 20


def test_r3_spends_two_theta() -> None:
    assert r3.THETA_NAMES == ("r3_months_in_loss", "r3_reopen_margin")
    assert len(r3.THETA_NAMES) == 2


def test_a_single_losing_month_does_not_shut_the_well(
    context: RuleContext,
) -> None:
    wells = (producer("42", RATE, CLEARLY_LOSING_WATERCUT, setpoint=RATE),)
    outcome = outcome_of(context, wells)
    assert outcome.decisions == ()
    assert [e.decision for e in outcome.trace] == ["HOLD_OPEN"]


def test_the_well_shuts_only_after_the_declared_run_of_losing_months(
    context: RuleContext,
) -> None:
    wells = (producer("42", RATE, CLEARLY_LOSING_WATERCUT, setpoint=RATE),)
    months = int(default_theta().values["r3_months_in_loss"])
    for elapsed in range(months - 1):
        outcome = outcome_of(
            context, wells, memory=memory_of(**{"42": WellMemory(months_in_loss=elapsed)})
        )
        assert outcome.decisions == ()
    final = outcome_of(
        context, wells, memory=memory_of(**{"42": WellMemory(months_in_loss=months - 1)})
    )
    assert [d.kind for d in final.decisions] == [EventKind.SHUT]


def memoryless(state, ctx, theta):
    shut = r0.apply(state, ctx, theta)
    if shut.decisions:
        return shut
    observation = next(iter(state.wells.values()))
    if observation.is_open:
        return shut
    margin = annual_margin_rub(
        ctx.normatives,
        ctx.oil_density_t_per_m3,
        observation.liquid_rate_m3_per_day,
        observation.watercut(ctx.oil_density_t_per_m3),
    )
    if margin <= 0.0:
        return shut
    return RuleOutcome(
        decisions=(
            ControlEvent(
                control_step=state.control_step,
                well=observation.well,
                kind=EventKind.OPEN,
            ),
        ),
        trace=(),
    )


def switch_count(context: RuleContext, months: int, rule) -> int:
    theta = default_theta()
    memory = memory_of()
    is_open = True
    switches = 0
    for step in range(months):
        wells = (producer("42", RATE, wobbling(step), setpoint=RATE, is_open=is_open),)
        state = state_of(*wells, control_step=step)
        ctx = replace(context, memory=memory)
        outcome = rule(state, ctx, theta)
        for event in outcome.decisions:
            if event.kind is EventKind.SHUT:
                is_open = False
            elif event.kind is EventKind.OPEN:
                is_open = True
            switches += 1
        memory = memory.updated("42", r3.advance(state, ctx, "42"))
    return switches


def test_r3_kills_the_chatter_of_a_memoryless_threshold(
    context: RuleContext,
) -> None:
    months = 24
    without = switch_count(context, months, memoryless)
    with_hysteresis = switch_count(context, months, r3.apply)
    assert without > months / 2
    assert with_hysteresis < without
    assert with_hysteresis * 4 <= months


def test_the_chatter_the_hysteresis_prevents_costs_a_million_an_event(
    context: RuleContext,
) -> None:
    months = 24
    without = switch_count(context, months, memoryless)
    with_hysteresis = switch_count(context, months, r3.apply)
    saved_rub = (without - with_hysteresis) * context.normatives.event_cost_rub
    assert saved_rub >= 10 * context.normatives.event_cost_rub


def test_a_well_at_the_threshold_does_not_switch_every_month(
    context: RuleContext,
) -> None:
    months = 36
    switches = switch_count(context, months, r3.apply)
    assert switches * 12 < months




def test_event_cost_of_the_chatter_is_written_into_the_trace(
    context: RuleContext,
) -> None:
    wells = (producer("42", RATE, CLEARLY_LOSING_WATERCUT, setpoint=RATE),)
    outcome = outcome_of(context, wells)
    assert outcome.trace
    for entry in outcome.trace:
        assert entry.inputs["event_cost_rub"] == (
            context.normatives.event_cost_rub
        )
        assert "months_in_loss" in entry.inputs
        assert "annual_margin_rub" in entry.inputs


def test_reopening_needs_a_margin_below_the_breakeven_not_merely_reaching_it(
    context: RuleContext,
) -> None:
    shut = (
        producer(
            "42", RATE, CLEARLY_PROFITABLE_WATERCUT, setpoint=RATE, is_open=False
        ),
    )
    outcome = outcome_of(context, shut)
    assert [d.kind for d in outcome.decisions] == [EventKind.OPEN]
    entry = outcome.trace[0]
    assert entry.inputs["reopen_watercut_threshold"] < entry.inputs[
        "breakeven_watercut"
    ]


def test_a_shut_well_just_above_the_reopen_threshold_stays_shut(
    context: RuleContext,
) -> None:
    breakeven = 0.0
    probe = outcome_of(
        context,
        (producer("42", RATE, CLEARLY_PROFITABLE_WATERCUT, setpoint=RATE, is_open=False),),
    )
    breakeven = probe.trace[0].inputs["breakeven_watercut"]
    margin = default_theta().values["r3_reopen_margin"]
    just_above = breakeven * (1.0 - margin) + 0.01
    outcome = outcome_of(
        context, (producer("42", RATE, just_above, setpoint=RATE, is_open=False),)
    )
    assert outcome.decisions == ()
    assert [e.decision for e in outcome.trace] == ["HOLD_SHUT"]


def test_zero_reopen_margin_makes_the_gate_the_breakeven_itself() -> None:
    assert r3.reopen_threshold(0.9, 0.0) == pytest.approx(0.9)
    assert r3.reopen_threshold(0.9, 0.5) == pytest.approx(0.45)


def test_a_longer_run_of_losing_months_shuts_later(
    context: RuleContext,
) -> None:
    wells = (producer("42", RATE, CLEARLY_LOSING_WATERCUT, setpoint=RATE),)
    patient = make_theta({"r3_months_in_loss": 9.0})
    hasty = make_theta({"r3_months_in_loss": 1.0})
    memory = memory_of(**{"42": WellMemory(months_in_loss=2)})
    assert outcome_of(context, wells, patient, memory).decisions == ()
    assert outcome_of(context, wells, hasty, memory).decisions != ()


def test_profitable_open_well_is_left_alone(context: RuleContext) -> None:
    wells = (producer("42", RATE, CLEARLY_PROFITABLE_WATERCUT, setpoint=RATE),)
    outcome = outcome_of(context, wells)
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_disabled_r3_makes_no_decisions_and_no_records(
    context: RuleContext,
) -> None:
    wells = (producer("42", RATE, CLEARLY_LOSING_WATERCUT, setpoint=RATE),)
    ctx = replace(context, memory=memory_of(**{"42": WellMemory(months_in_loss=9)}))
    off = apply_rule(
        Rule.R3,
        state_of(*wells),
        ctx,
        default_theta(),
        RuleFlags().with_disabled(Rule.R3),
    )
    assert off.decisions == ()
    assert off.trace == ()


def test_memory_counts_losing_and_profitable_months(
    context: RuleContext,
) -> None:
    losing = state_of(producer("42", RATE, CLEARLY_LOSING_WATERCUT, setpoint=RATE))
    profitable = state_of(
        producer("42", RATE, CLEARLY_PROFITABLE_WATERCUT, setpoint=RATE)
    )
    ctx = replace(context, memory=memory_of())
    after_loss = r3.advance(losing, ctx, "42")
    assert after_loss.months_in_loss == 1
    ctx = replace(context, memory=memory_of(**{"42": after_loss}))
    after_profit = r3.advance(profitable, ctx, "42")
    assert after_profit.months_in_loss == 0
    assert after_profit.months_in_profit == 1
