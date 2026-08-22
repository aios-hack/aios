from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core.contracts import EventKind, NormativeSet, Rule

from backend.domain.policy import (
    SPECS,
    RuleContext,
    RuleFlags,
    apply_rule,
    breakeven_watercut,
    default_theta,
    make_theta,
)
from backend.domain.policy.rules import r0
from backend.domain.policy.tests.conftest import (
    OIL_DENSITY_SECOND_REGION_T_PER_M3,
    OIL_DENSITY_T_PER_M3,
    producer,
    state_of,
    with_oil_price,
)

EXPECTED_FIRST_REGION = {
    5.0: 0.915,
    10.0: 0.951,
    20.0: 0.969,
    30.0: 0.975,
    50.0: 0.980,
    100.0: 0.983,
}

EXPECTED_SECOND_REGION = {
    5.0: 0.917,
    10.0: 0.952,
    20.0: 0.970,
    30.0: 0.975,
    50.0: 0.980,
    100.0: 0.984,
}


@pytest.mark.parametrize("rate,expected", sorted(EXPECTED_FIRST_REGION.items()))
def test_threshold_table_first_region(
    normatives: NormativeSet, rate: float, expected: float
) -> None:
    got = breakeven_watercut(normatives, OIL_DENSITY_T_PER_M3, rate)
    assert round(got, 3) == expected


@pytest.mark.parametrize("rate,expected", sorted(EXPECTED_SECOND_REGION.items()))
def test_threshold_table_second_region_to_published_precision(
    normatives: NormativeSet, rate: float, expected: float
) -> None:
    got = breakeven_watercut(
        normatives, OIL_DENSITY_SECOND_REGION_T_PER_M3, rate
    )
    assert got == pytest.approx(expected, abs=0.001)


def test_threshold_grows_with_rate(normatives: NormativeSet) -> None:
    rates = sorted(EXPECTED_FIRST_REGION)
    thresholds = [
        breakeven_watercut(normatives, OIL_DENSITY_T_PER_M3, rate) for rate in rates
    ]
    assert thresholds == sorted(thresholds)


def test_density_in_kg_per_m3_rejected(normatives: NormativeSet) -> None:
    with pytest.raises(ValueError):
        breakeven_watercut(normatives, 913.1, 20.0)


def test_kg_per_m3_would_shift_threshold_by_thousand(
    normatives: NormativeSet,
) -> None:
    correct = breakeven_watercut(normatives, OIL_DENSITY_T_PER_M3, 20.0)
    margin = (
        normatives.price_oil_rub_per_t
        - normatives.deductions_rub_per_t
        - normatives.opex_oil_rub_per_t
    )
    required = normatives.opex_liquid_rub_per_t + (
        normatives.opex_wellstock_rub_per_well_year / (365.0 * 20.0)
    )
    wrong = 1.0 - required / (913.1 * margin)
    assert wrong > 0.9999
    assert correct < 0.97


def test_r0_has_zero_theta_parameters() -> None:
    assert r0.THETA_NAMES == ()


def test_theta_does_not_move_r0_decision(context: RuleContext) -> None:
    state = state_of(producer("42", liquid_rate_m3_per_day=5.0, watercut=0.98))
    flags = RuleFlags()
    baseline = apply_rule(Rule.R0, state, context, default_theta(), flags)
    for spec in SPECS:
        for value in (spec.low, spec.high):
            moved = make_theta({spec.name: value})
            other = apply_rule(Rule.R0, state, context, moved, flags)
            assert other == baseline


def test_oil_price_moves_r0_decision(
    normatives: NormativeSet, context: RuleContext
) -> None:
    state = state_of(producer("42", liquid_rate_m3_per_day=20.0, watercut=0.975))
    flags = RuleFlags()
    theta = default_theta()

    at_base = apply_rule(Rule.R0, state, context, theta, flags)
    assert [event.well for event in at_base.decisions] == ["42"]

    richer = replace(context, normatives=with_oil_price(normatives, 40_000.0))
    at_high_price = apply_rule(Rule.R0, state, richer, theta, flags)
    assert at_high_price.decisions == ()

    poorer = replace(context, normatives=with_oil_price(normatives, 22_000.0))
    at_low_price = apply_rule(Rule.R0, state, poorer, theta, flags)
    assert [event.kind for event in at_low_price.decisions] == [EventKind.SHUT]


def test_profitable_well_is_not_shut(context: RuleContext) -> None:
    state = state_of(producer("42", liquid_rate_m3_per_day=20.0, watercut=0.90))
    outcome = apply_rule(Rule.R0, state, context, default_theta(), RuleFlags())
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_trace_carries_decision_numbers(context: RuleContext) -> None:
    state = state_of(producer("42", liquid_rate_m3_per_day=5.0, watercut=0.99))
    outcome = apply_rule(Rule.R0, state, context, default_theta(), RuleFlags())
    entry = outcome.trace[0]
    assert entry.rule is Rule.R0
    assert entry.decision == "SHUT"
    assert entry.inputs["annual_margin_rub"] < 0.0
    assert entry.inputs["watercut"] > entry.inputs["breakeven_watercut"]
    assert entry.inputs["oil_density_t_per_m3"] == OIL_DENSITY_T_PER_M3
    assert entry.inputs["oil_margin_rub_per_t"] == 8360.0


def test_zero_rate_is_not_evaluated(context: RuleContext) -> None:
    state = state_of(producer("42", liquid_rate_m3_per_day=0.0, watercut=0.0))
    outcome = apply_rule(Rule.R0, state, context, default_theta(), RuleFlags())
    assert outcome.decisions == ()
