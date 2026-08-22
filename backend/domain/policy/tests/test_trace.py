from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core.contracts import N_INTERVALS, Rule, TraceEntry

from backend.domain.policy import (
    IMPLEMENTED_RULES,
    RuleContext,
    RuleFlags,
    RunTrace,
    TraceCollector,
    all_off,
    apply_all,
    collect,
    default_theta,
    dumps,
    explain,
    loads,
    run_trace,
    superseded,
    to_payload,
    trace_hash,
)
from backend.domain.policy.tests.conftest import DECIDING_WELLS, deciding_context, state_of

RUN_STEPS = (0, 1, 2)

WELLS = DECIDING_WELLS


def run(context: RuleContext, flags: RuleFlags):
    ctx = deciding_context(context)
    theta = default_theta()
    return run_trace(
        RUN_STEPS,
        lambda step: apply_all(
            state_of(*WELLS, control_step=step), ctx, theta, flags
        ),
        flags,
    )


def test_trace_is_collected_over_the_whole_run(context: RuleContext) -> None:
    result = run(context, RuleFlags())
    assert result.trace.steps() == RUN_STEPS
    assert len(result.trace) > len(RUN_STEPS)


def test_every_decision_carries_a_trace_entry(context: RuleContext) -> None:
    result = run(context, RuleFlags())
    traced = {(e.control_step, e.well) for e in result.trace.entries}
    for event in result.decisions:
        assert (event.control_step, event.well) in traced


def test_one_entry_per_fired_rule_for_a_well_step(context: RuleContext) -> None:
    result = run(context, RuleFlags())
    for (well, step), count in result.trace.count_by_well_step().items():
        fired = {e.rule for e in result.trace.at(step, well)}
        assert count == len(fired)


def test_filter_by_rule_well_and_step(context: RuleContext) -> None:
    result = run(context, RuleFlags())
    trace = result.trace
    assert all(e.rule is Rule.R2 for e in trace.by_rule(Rule.R2))
    assert all(e.well == "43" for e in trace.by_well("43"))
    assert all(e.control_step == 1 for e in trace.by_step(1))
    narrowed = trace.select(rule=Rule.R2, well="43", control_step=1)
    assert len(narrowed) == 1
    assert narrowed[0].rule is Rule.R2


def test_each_well_month_says_which_rule_fired_with_what_numbers(
    context: RuleContext,
) -> None:
    result = run(context, RuleFlags())
    entries = result.trace.at(0, "42")
    assert entries
    for entry in entries:
        assert entry.rule in IMPLEMENTED_RULES
        assert entry.decision
        assert entry.inputs
    lines = explain(result.trace, 0, "42")
    assert lines
    assert all("=" in line for line in lines)


def test_disabled_rule_leaves_neither_decision_nor_record(
    context: RuleContext,
) -> None:
    for rule in IMPLEMENTED_RULES:
        flags = RuleFlags().with_disabled(rule)
        result = run(context, flags)
        assert result.trace.by_rule(rule) == ()
        assert rule not in result.trace.rules_fired()
        assert rule not in result.trace.count_by_rule()


def test_all_rules_off_gives_an_empty_run(context: RuleContext) -> None:
    result = run(context, all_off())
    assert result.decisions == ()
    assert len(result.trace) == 0
    assert result.trace.rules_fired() == ()


def test_disabling_a_rule_removes_exactly_its_own_records(
    context: RuleContext,
) -> None:
    baseline_flags = RuleFlags()
    baseline = run(context, baseline_flags).trace.count_by_rule()
    for rule in IMPLEMENTED_RULES:
        if not baseline_flags.is_on(rule):
            continue
        flags = baseline_flags.with_disabled(rule)
        ablated = run(context, flags).trace.count_by_rule()
        assert rule not in ablated
        released = superseded(baseline_flags) - superseded(flags)
        for other in IMPLEMENTED_RULES:
            if other is rule or other in released:
                continue
            if not baseline_flags.is_on(other):
                continue
            assert ablated[other] == baseline[other]


def test_disabling_the_gate_hands_the_decision_back_to_the_rule_it_covered(
    context: RuleContext,
) -> None:
    assert Rule.R0 in superseded(RuleFlags())
    with_gate = run(context, RuleFlags()).trace
    without_gate = run(context, RuleFlags().with_disabled(Rule.R3)).trace
    assert with_gate.by_rule(Rule.R0) == ()
    assert without_gate.by_rule(Rule.R0) != ()


def test_trace_rejects_a_record_from_a_disabled_rule(
    context: RuleContext,
) -> None:
    result = run(context, RuleFlags())
    with pytest.raises(ValueError, match="выключено флагом"):
        RunTrace(
            entries=result.trace.entries,
            flags=RuleFlags().with_disabled(Rule.R3),
        )


def test_collector_rejects_an_outcome_from_a_disabled_rule(
    context: RuleContext,
) -> None:
    ctx = deciding_context(context)
    enabled = apply_all(state_of(*WELLS), ctx, default_theta(), RuleFlags())
    collector = TraceCollector(RuleFlags().with_disabled(Rule.R2))
    with pytest.raises(ValueError, match="выключено флагом"):
        collector.add(enabled)


def test_trace_rejects_a_record_without_numbers() -> None:
    with pytest.raises(ValueError, match="без чисел"):
        RunTrace(
            entries=(
                TraceEntry(
                    control_step=0,
                    well="42",
                    rule=Rule.R0,
                    inputs={},
                    decision="SHUT",
                ),
            ),
            flags=RuleFlags(),
        )


def test_trace_rejects_the_terminal_step() -> None:
    with pytest.raises(ValueError, match="вне"):
        RunTrace(
            entries=(
                TraceEntry(
                    control_step=N_INTERVALS,
                    well="42",
                    rule=Rule.R0,
                    inputs={"liquid_rate_m3_per_day": 1.0},
                    decision="SHUT",
                ),
            ),
            flags=RuleFlags(),
        )


def test_serialization_round_trips(context: RuleContext) -> None:
    original = run(context, RuleFlags()).trace
    restored = loads(dumps(original))
    assert len(restored) == len(original)
    assert restored.flags.enabled == original.flags.enabled
    assert trace_hash(restored) == trace_hash(original)


def test_serialized_trace_carries_the_flags(context: RuleContext) -> None:
    flags = RuleFlags().with_disabled(Rule.R2)
    payload = to_payload(run(context, flags).trace)
    assert payload["flags"][Rule.R2.value] is False
    assert payload["flags"][Rule.R0.value] is True


def test_serialization_without_flags_is_rejected(context: RuleContext) -> None:
    text = dumps(run(context, RuleFlags()).trace).replace('"flags"', '"нет"')
    with pytest.raises(ValueError, match="флаг"):
        loads(text)


def test_trace_hash_is_deterministic_and_flag_sensitive(
    context: RuleContext,
) -> None:
    first = run(context, RuleFlags()).trace
    second = run(context, RuleFlags()).trace
    disabled = run(context, RuleFlags().with_disabled(Rule.R2)).trace
    assert trace_hash(first) == trace_hash(second)
    assert trace_hash(first) != trace_hash(disabled)


def test_collect_accepts_outcomes_directly(context: RuleContext) -> None:
    ctx = deciding_context(context)
    theta = default_theta()
    flags = RuleFlags()
    outcomes = [
        apply_all(state_of(*WELLS, control_step=step), ctx, theta, flags)
        for step in RUN_STEPS
    ]
    result = collect(outcomes, flags)
    assert result.trace.steps() == RUN_STEPS


def test_silent_enabled_rules_are_named(context: RuleContext) -> None:
    result = run(context, RuleFlags())
    silent = set(result.trace.silent_rules())
    fired = set(result.trace.rules_fired())
    assert silent & fired == set()
    for rule in Rule:
        if not result.trace.flags.is_on(rule):
            assert rule not in silent
