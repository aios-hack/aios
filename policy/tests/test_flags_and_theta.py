from __future__ import annotations

from dataclasses import replace

import pytest

from contracts import Rule, Theta
from contracts.policy import MAX_THETA_PARAMS

from policy import (
    ADMISSION_CRITERIA,
    DEFAULT_RULE_FLAGS,
    IMPLEMENTED_RULES,
    SPECS,
    THETA_NAMES_BY_RULE,
    RuleContext,
    RuleFlags,
    all_off,
    apply_all,
    apply_rule,
    budget_by_rule,
    budget_free,
    budget_used,
    declared_bounds,
    default_theta,
    make_theta,
    specs_for,
)
from policy.theta import RESERVED_FOR_R7, total_budget_ok
from policy.tests.conftest import DECIDING_WELLS, deciding_context, state_of

DECIDING_STATE_WELLS = DECIDING_WELLS


def test_theta_total_within_contract_cap() -> None:
    assert len(SPECS) + RESERVED_FOR_R7 <= MAX_THETA_PARAMS
    assert total_budget_ok()


def test_theta_count_per_rule() -> None:
    assert len(specs_for(Rule.R0)) == 0
    assert len(specs_for(Rule.R1)) == 1
    assert len(specs_for(Rule.R2)) == 2
    assert len(specs_for(Rule.R3)) == 2
    assert len(specs_for(Rule.R4)) == 0
    assert len(specs_for(Rule.R5)) == 2
    assert len(specs_for(Rule.R6)) == 1
    assert len(specs_for(Rule.R7)) == 0


def test_theta_budget_across_all_rules_is_within_ten() -> None:
    assert budget_used() == 8
    assert budget_free() == 2
    assert budget_used() + budget_free() == MAX_THETA_PARAMS
    per_rule = budget_by_rule()
    assert sum(per_rule.values()) == budget_used()
    assert per_rule[Rule.R7] == 0


def test_the_registry_names_every_theta_of_every_implemented_rule() -> None:
    for rule in IMPLEMENTED_RULES:
        declared = {spec.name for spec in specs_for(rule)}
        assert declared == set(THETA_NAMES_BY_RULE[rule])


def test_every_theta_has_declared_bounds() -> None:
    bounds = declared_bounds()
    assert set(bounds) == {spec.name for spec in SPECS}
    for spec in SPECS:
        assert bounds[spec.name] == (spec.low, spec.high)
        assert spec.low < spec.high


def test_default_theta_is_valid_contract_object() -> None:
    theta = default_theta()
    assert isinstance(theta, Theta)
    assert set(theta.values) == set(theta.bounds)
    for name, value in theta.values.items():
        low, high = theta.bounds[name]
        assert low <= value <= high


def test_theta_names_are_unique_across_rules() -> None:
    names = [name for rule in Rule for name in THETA_NAMES_BY_RULE.get(rule, ())]
    assert len(names) == len(set(names))


def test_unknown_theta_name_rejected() -> None:
    with pytest.raises(ValueError):
        make_theta({"r2_magic_coefficient": 0.5})


def test_theta_over_cap_rejected_by_contract() -> None:
    values = {f"p{i}": 0.0 for i in range(MAX_THETA_PARAMS + 1)}
    with pytest.raises(ValueError):
        Theta(values=values, bounds={name: (0.0, 1.0) for name in values})


def test_disabled_rule_makes_no_decisions_and_no_trace(context: RuleContext) -> None:
    ctx = deciding_context(context)
    state = state_of(*DECIDING_STATE_WELLS)
    theta = default_theta()
    for rule in IMPLEMENTED_RULES:
        on = apply_rule(rule, state, ctx, theta, RuleFlags())
        off = apply_rule(rule, state, ctx, theta, RuleFlags().with_disabled(rule))
        assert on.decisions != () or on.trace != ()
        assert off.decisions == ()
        assert off.trace == ()


def test_all_rules_off_produces_empty_policy(context: RuleContext) -> None:
    ctx = deciding_context(context)
    state = state_of(*DECIDING_STATE_WELLS)
    outcome = apply_all(state, ctx, default_theta(), all_off())
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_trace_of_disabled_rule_absent_from_combined_run(context: RuleContext) -> None:
    ctx = deciding_context(context)
    state = state_of(*DECIDING_STATE_WELLS)
    flags = RuleFlags().with_disabled(Rule.R2)
    outcome = apply_all(state, ctx, default_theta(), flags)
    assert Rule.R2 not in {entry.rule for entry in outcome.trace}
    assert Rule.R3 in {entry.rule for entry in outcome.trace}


def test_rules_are_deterministic_on_the_same_input(context: RuleContext) -> None:
    ctx = deciding_context(context)
    state = state_of(*DECIDING_STATE_WELLS)
    theta = default_theta()
    first = apply_all(state, ctx, theta, RuleFlags())
    second = apply_all(state, ctx, theta, RuleFlags())
    assert first == second
    assert [(e.well, e.kind, e.value) for e in first.decisions] == [
        (e.well, e.kind, e.value) for e in second.decisions
    ]


def test_every_trace_entry_has_numbers(context: RuleContext) -> None:
    ctx = deciding_context(context)
    state = state_of(*DECIDING_STATE_WELLS)
    outcome = apply_all(state, ctx, default_theta(), RuleFlags())
    assert outcome.trace
    for entry in outcome.trace:
        assert entry.inputs
        assert all(isinstance(value, float) for value in entry.inputs.values())
        assert entry.decision


def test_trace_entries_are_bound_to_the_current_control_step(
    context: RuleContext,
) -> None:
    ctx = deciding_context(context)
    state = state_of(*DECIDING_STATE_WELLS, control_step=17)
    outcome = apply_all(state, ctx, default_theta(), RuleFlags())
    assert {entry.control_step for entry in outcome.trace} == {17}
    assert {event.control_step for event in outcome.decisions} == {17}


def test_every_implemented_rule_states_admission_criterion() -> None:
    for rule in IMPLEMENTED_RULES:
        criterion = ADMISSION_CRITERIA[rule]
        assert criterion.endswith(".")
        assert len(criterion.split()) <= 20


def test_unimplemented_rules_are_off_by_default_and_raise(
    context: RuleContext,
) -> None:
    for rule in Rule:
        if rule in IMPLEMENTED_RULES:
            assert DEFAULT_RULE_FLAGS[rule] is True
            continue
        assert DEFAULT_RULE_FLAGS[rule] is False
        with pytest.raises(NotImplementedError):
            apply_rule(
                rule,
                state_of(*DECIDING_STATE_WELLS),
                context,
                default_theta(),
                RuleFlags(),
            )


def test_flags_required_for_all_eight_rules() -> None:
    with pytest.raises(ValueError):
        RuleFlags(enabled={Rule.R0: True})
