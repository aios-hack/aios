from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core.contracts import Constraints, EventKind, Rule

from backend.domain.policy import (
    RuleContext,
    RuleFlags,
    allocate_field,
    apply_rule,
    decide_group,
    default_theta,
    group_liquid_demand_rub_per_day,
    run_step,
)
from backend.domain.policy.budget import (
    liquid_limit_for_step,
    production_floor_for_step,
)
from backend.domain.policy.rules import r2
from backend.domain.policy.tests.conftest import (
    groups_of,
    influence_of,
    injector,
    memory_of,
    producer,
    state_of,
)

FIELD_INJECTION_LIMIT_M3_PER_DAY = 600.0
FIELD_LIQUID_LIMIT_M3_PER_DAY = 80.0
TIGHT_LIQUID_LIMIT_M3_PER_DAY = 40.0
GROUP_A = "G-A"
GROUP_B = "G-B"
TOLERANCE_M3_PER_DAY = 1e-9


def two_group_state():
    return state_of(
        producer("p1", liquid_rate_m3_per_day=60.0, watercut=0.30, setpoint=60.0),
        producer("p2", liquid_rate_m3_per_day=50.0, watercut=0.95, setpoint=50.0),
        injector("i1", injection_rate_m3_per_day=150.0),
        injector("i2", injection_rate_m3_per_day=150.0),
    )


def two_group_context(context: RuleContext) -> RuleContext:
    influence = influence_of(
        producers=("p1", "p2"),
        injectors=("i1", "i2"),
        matrix=((0.5, 0.02), (0.02, 0.5)),
    )
    return replace(
        context,
        influence=influence,
        groups=groups_of({GROUP_A: ("p1", "i1"), GROUP_B: ("p2", "i2")}),
        injection_budget_m3_per_day=FIELD_INJECTION_LIMIT_M3_PER_DAY,
        group_injection_m3_per_day={GROUP_A: 150.0, GROUP_B: 150.0},
        group_offtake_m3_per_day={GROUP_A: 60.0, GROUP_B: 50.0},
        memory=memory_of(),
    )


def one_group_state():
    return state_of(
        producer("p1", liquid_rate_m3_per_day=60.0, watercut=0.30, setpoint=60.0),
        producer("p2", liquid_rate_m3_per_day=50.0, watercut=0.35, setpoint=50.0),
        injector("i1", injection_rate_m3_per_day=150.0),
    )


def one_group_context(context: RuleContext) -> RuleContext:
    influence = influence_of(
        producers=("p1", "p2"),
        injectors=("i1",),
        matrix=((0.5,), (0.4,)),
    )
    return replace(
        context,
        influence=influence,
        groups=groups_of({GROUP_A: ("p1", "p2", "i1")}),
        injection_budget_m3_per_day=FIELD_INJECTION_LIMIT_M3_PER_DAY,
        group_injection_m3_per_day={GROUP_A: 150.0},
        group_offtake_m3_per_day={GROUP_A: 110.0},
        memory=memory_of(),
    )


def r1_and_r2_flags() -> RuleFlags:
    return RuleFlags(enabled={rule: rule in (Rule.R1, Rule.R2) for rule in Rule})


def only_r1_flags() -> RuleFlags:
    return RuleFlags(enabled={rule: rule is Rule.R1 for rule in Rule})


def test_liquid_limit_for_step_reads_the_year_from_constraints() -> None:
    constraints = Constraints(liquid_limits={2010: 38000.0, 2011: 36000.0})
    assert liquid_limit_for_step(constraints, 2010, 0) == 38000.0
    assert liquid_limit_for_step(constraints, 2011, 12) == 36000.0


def test_liquid_limit_is_none_when_the_year_has_no_limit() -> None:
    constraints = Constraints(liquid_limits={2010: 38000.0})
    assert liquid_limit_for_step(constraints, 2012, 0) is None


def test_liquid_limit_is_none_when_constraints_are_empty() -> None:
    assert liquid_limit_for_step(Constraints(), 2010, 0) is None


def test_liquid_limit_refuses_a_step_outside_the_horizon() -> None:
    constraints = Constraints(liquid_limits={2010: 1.0})
    with pytest.raises(ValueError, match="вне 0"):
        liquid_limit_for_step(constraints, 2010, -1)
    with pytest.raises(ValueError, match="вне 0"):
        liquid_limit_for_step(constraints, 2010, 224)


def test_liquid_limit_refuses_a_negative_limit() -> None:
    constraints = Constraints(liquid_limits={2010: -1.0})
    with pytest.raises(ValueError, match="отрицателен"):
        liquid_limit_for_step(constraints, 2010, 0)


def test_production_floor_for_step_reads_the_year() -> None:
    constraints = Constraints(production_floors={2010: 900.0})
    assert production_floor_for_step(constraints, 2010, 5) == 900.0
    assert production_floor_for_step(constraints, 2011, 5) is None


def test_context_defaults_carry_no_liquid_budget(context: RuleContext) -> None:
    assert context.liquid_budget_m3_per_day is None
    assert context.group_liquid_budget_m3_per_day == {}


def test_context_refuses_a_negative_liquid_budget(context: RuleContext) -> None:
    with pytest.raises(ValueError, match="отрицательный лимит жидкости"):
        replace(context, liquid_budget_m3_per_day=-1.0)


def test_context_refuses_a_negative_group_liquid_quota(
    context: RuleContext,
) -> None:
    with pytest.raises(ValueError, match="отрицательная квота жидкости"):
        replace(context, group_liquid_budget_m3_per_day={GROUP_A: -1.0})


def test_without_a_liquid_limit_the_allocation_is_unchanged(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    allocation = allocate_field(
        state, scoped, only_r1_flags(), FIELD_INJECTION_LIMIT_M3_PER_DAY
    )
    assert allocation.field_liquid_limit_m3_per_day is None
    assert allocation.allocated_liquid_m3_per_day() == 0.0
    for limit in allocation.limits:
        assert limit.liquid_m3_per_day is None
        assert limit.liquid_share_of_field is None
    decisions = [
        entry.entry.decision
        for entry in allocation.trace
    ]
    assert decisions == ["SET_GROUP_LIMIT", "SET_GROUP_LIMIT"]


def test_without_a_liquid_limit_the_step_is_bit_for_bit_the_same(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    theta = default_theta()
    flags = r1_and_r2_flags()
    before = run_step(
        state,
        scoped,
        theta,
        flags,
        field_limit_m3_per_day=FIELD_INJECTION_LIMIT_M3_PER_DAY,
    )
    after = run_step(
        state,
        scoped,
        theta,
        flags,
        field_limit_m3_per_day=FIELD_INJECTION_LIMIT_M3_PER_DAY,
        field_liquid_limit_m3_per_day=None,
    )
    assert before.decisions == after.decisions
    assert before.trace.entries == after.trace.entries


def test_group_quotas_never_exceed_the_field_liquid_limit(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(
        two_group_state(),
        scoped,
        r1_and_r2_flags(),
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    assert allocation.field_liquid_limit_m3_per_day == FIELD_LIQUID_LIMIT_M3_PER_DAY
    total = allocation.allocated_liquid_m3_per_day()
    assert total <= FIELD_LIQUID_LIMIT_M3_PER_DAY + TOLERANCE_M3_PER_DAY
    assert total == pytest.approx(FIELD_LIQUID_LIMIT_M3_PER_DAY)


def test_liquid_shares_sum_to_one_when_any_group_earns(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(
        two_group_state(),
        scoped,
        r1_and_r2_flags(),
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    shares = [limit.liquid_share_of_field for limit in allocation.limits]
    assert sum(share or 0.0 for share in shares) == pytest.approx(1.0)


def test_clean_group_gets_more_liquid_quota_than_the_flooded_one(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(
        two_group_state(),
        scoped,
        r1_and_r2_flags(),
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    clean = allocation.of(GROUP_A).liquid_m3_per_day
    flooded = allocation.of(GROUP_B).liquid_m3_per_day
    assert clean is not None and flooded is not None
    assert clean > flooded


def test_marginal_value_of_offtake_is_margin_times_rate(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    demand, offtake, counted = group_liquid_demand_rub_per_day(
        state, scoped, ("p1", "i1")
    )
    observation = state.wells["p1"]
    watercut = observation.watercut(scoped.oil_density_t_per_m3)
    margin = (
        (1.0 - watercut)
        * scoped.oil_density_t_per_m3
        * (
            scoped.normatives.price_oil_rub_per_t
            - scoped.normatives.deductions_rub_per_t
            - scoped.normatives.opex_oil_rub_per_t
        )
        - scoped.normatives.opex_liquid_rub_per_t
    )
    assert offtake == pytest.approx(60.0)
    assert counted == 1
    assert demand == pytest.approx(margin * 60.0)


def test_a_group_without_producers_gets_no_liquid_quota(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    demand, offtake, counted = group_liquid_demand_rub_per_day(
        two_group_state(), scoped, ("i1",)
    )
    assert (demand, offtake, counted) == (0.0, 0.0, 0)


def test_field_allocation_refuses_a_negative_liquid_limit(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    with pytest.raises(ValueError, match="отрицательный лимит жидкости поля"):
        allocate_field(
            two_group_state(),
            scoped,
            r1_and_r2_flags(),
            FIELD_INJECTION_LIMIT_M3_PER_DAY,
            -1.0,
        )


def test_trace_carries_the_group_liquid_limit(context: RuleContext) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(
        two_group_state(),
        scoped,
        r1_and_r2_flags(),
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    liquid = [
        entry
        for entry in allocation.trace
        if entry.entry.decision == "SET_GROUP_LIQUID_LIMIT"
    ]
    assert len(liquid) == 2
    for entry in liquid:
        assert entry.entry.rule is Rule.R2
        assert (
            entry.entry.inputs["field_liquid_limit_m3_per_day"]
            == FIELD_LIQUID_LIMIT_M3_PER_DAY
        )
        assert "group_liquid_limit_m3_per_day" in entry.entry.inputs
        assert "liquid_share_of_field" in entry.entry.inputs
    granted = sum(
        entry.entry.inputs["group_liquid_limit_m3_per_day"] for entry in liquid
    )
    assert granted <= FIELD_LIQUID_LIMIT_M3_PER_DAY + TOLERANCE_M3_PER_DAY


def test_run_step_trace_carries_the_group_liquid_limit(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    result = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        r1_and_r2_flags(),
        field_limit_m3_per_day=FIELD_INJECTION_LIMIT_M3_PER_DAY,
        field_liquid_limit_m3_per_day=FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    decisions = {entry.entry.decision for entry in result.trace.entries}
    assert "SET_GROUP_LIQUID_LIMIT" in decisions


def test_no_liquid_trace_when_r2_is_off(context: RuleContext) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(
        two_group_state(),
        scoped,
        only_r1_flags(),
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    decisions = {entry.entry.decision for entry in allocation.trace}
    assert "SET_GROUP_LIQUID_LIMIT" not in decisions


def test_r2_caps_a_single_setpoint_at_the_group_quota(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("p1", liquid_rate_m3_per_day=60.0, watercut=0.10, setpoint=60.0)
    )
    theta = default_theta()
    free = apply_rule(Rule.R2, state, context, theta, RuleFlags())
    scoped = replace(context, liquid_budget_m3_per_day=20.0)
    capped = apply_rule(Rule.R2, state, scoped, theta, RuleFlags())
    assert free.decisions[0].value is not None
    assert free.decisions[0].value > 20.0
    assert capped.decisions[0].value == pytest.approx(20.0)
    assert capped.trace[0].inputs["group_liquid_budget_m3_per_day"] == 20.0


def test_r2_trace_omits_the_quota_when_there_is_none(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("p1", liquid_rate_m3_per_day=60.0, watercut=0.10, setpoint=60.0)
    )
    outcome = apply_rule(Rule.R2, state, context, default_theta(), RuleFlags())
    assert "group_liquid_budget_m3_per_day" not in outcome.trace[0].inputs


def test_r2_theta_and_rule_identity_are_untouched() -> None:
    assert r2.RULE is Rule.R2
    assert r2.THETA_NAMES == ("r2_watercut_pivot", "r2_gain")


def test_group_scales_setpoints_down_to_its_liquid_quota(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    flags = r1_and_r2_flags()
    allocation = allocate_field(
        state,
        scoped,
        flags,
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    limit = allocation.of(GROUP_A)
    assert limit.liquid_m3_per_day is not None
    decision = decide_group(state, scoped, default_theta(), flags, limit)
    assert decision.requested_liquid_m3_per_day is not None
    assert (
        decision.requested_liquid_m3_per_day
        <= limit.liquid_m3_per_day + TOLERANCE_M3_PER_DAY
    )
    lrat = {
        event.well: event.value
        for event in decision.decisions
        if event.kind is EventKind.SET_LRAT
    }
    assert lrat["p1"] is not None
    assert lrat["p1"] <= limit.liquid_m3_per_day + TOLERANCE_M3_PER_DAY


def test_group_records_the_scale_down_in_the_trace(context: RuleContext) -> None:
    scoped = one_group_context(context)
    state = one_group_state()
    flags = r1_and_r2_flags()
    allocation = allocate_field(
        state,
        scoped,
        flags,
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        TIGHT_LIQUID_LIMIT_M3_PER_DAY,
    )
    limit = allocation.of(GROUP_A)
    decision = decide_group(state, scoped, default_theta(), flags, limit)
    scale = [
        entry
        for entry in decision.trace
        if entry.entry.decision == "SCALE_TO_GROUP_LIQUID_LIMIT"
    ]
    assert len(scale) == 1
    inputs = scale[0].entry.inputs
    assert inputs["group_liquid_limit_scale"] < 1.0
    assert (
        inputs["granted_liquid_m3_per_day"]
        <= inputs["group_liquid_limit_m3_per_day"] + TOLERANCE_M3_PER_DAY
    )


def test_no_scale_down_when_the_quota_is_generous(context: RuleContext) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    flags = r1_and_r2_flags()
    allocation = allocate_field(
        state,
        scoped,
        flags,
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        100_000.0,
    )
    limit = allocation.of(GROUP_A)
    decision = decide_group(state, scoped, default_theta(), flags, limit)
    decisions = {entry.entry.decision for entry in decision.trace}
    assert "SCALE_TO_GROUP_LIQUID_LIMIT" not in decisions


def test_untouched_producers_are_counted_against_the_quota(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    flags = only_r1_flags()
    allocation = allocate_field(
        state,
        scoped,
        flags,
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
        10.0,
    )
    limit = allocation.of(GROUP_A)
    assert limit.liquid_m3_per_day is not None
    decision = decide_group(state, scoped, default_theta(), flags, limit)
    assert decision.requested_liquid_m3_per_day is not None
    assert (
        decision.requested_liquid_m3_per_day
        <= limit.liquid_m3_per_day + TOLERANCE_M3_PER_DAY
    )


def test_whole_field_offtake_stays_under_the_limit_at_this_step(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    result = run_step(
        state,
        scoped,
        default_theta(),
        r1_and_r2_flags(),
        field_limit_m3_per_day=FIELD_INJECTION_LIMIT_M3_PER_DAY,
        field_liquid_limit_m3_per_day=FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    commanded = {
        event.well: event.value
        for event in result.decisions
        if event.kind is EventKind.SET_LRAT and event.value is not None
    }
    total = 0.0
    for well, observation in state.wells.items():
        if observation.role.value != "PROD":
            continue
        total += commanded.get(well, observation.liquid_rate_m3_per_day)
    assert total <= FIELD_LIQUID_LIMIT_M3_PER_DAY + TOLERANCE_M3_PER_DAY


def test_a_zero_liquid_limit_shuts_the_offtake_down(context: RuleContext) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    result = run_step(
        state,
        scoped,
        default_theta(),
        r1_and_r2_flags(),
        field_limit_m3_per_day=FIELD_INJECTION_LIMIT_M3_PER_DAY,
        field_liquid_limit_m3_per_day=0.0,
    )
    for event in result.decisions:
        if event.kind is EventKind.SET_LRAT and event.value is not None:
            assert event.value == pytest.approx(0.0)


def test_the_quota_is_a_daily_rate_the_validator_compares_per_step(
    context: RuleContext,
) -> None:
    constraints = Constraints(liquid_limits={2010: FIELD_LIQUID_LIMIT_M3_PER_DAY})
    scoped = replace(two_group_context(context), constraints=constraints)
    state = two_group_state()
    limit = liquid_limit_for_step(constraints, 2010, state.control_step)
    assert limit == FIELD_LIQUID_LIMIT_M3_PER_DAY
    result = run_step(
        state,
        scoped,
        default_theta(),
        r1_and_r2_flags(),
        field_limit_m3_per_day=FIELD_INJECTION_LIMIT_M3_PER_DAY,
        field_liquid_limit_m3_per_day=limit,
    )
    commanded = {
        event.well: event.value
        for event in result.decisions
        if event.kind is EventKind.SET_LRAT and event.value is not None
    }
    step_total = sum(
        commanded.get(well, observation.liquid_rate_m3_per_day)
        for well, observation in state.wells.items()
        if observation.role.value == "PROD"
    )
    assert step_total <= limit + TOLERANCE_M3_PER_DAY


def test_the_field_limit_is_read_from_the_context_when_not_passed(
    context: RuleContext,
) -> None:
    scoped = replace(
        two_group_context(context),
        liquid_budget_m3_per_day=FIELD_LIQUID_LIMIT_M3_PER_DAY,
    )
    allocation = allocate_field(
        two_group_state(),
        scoped,
        r1_and_r2_flags(),
        FIELD_INJECTION_LIMIT_M3_PER_DAY,
    )
    assert allocation.field_liquid_limit_m3_per_day == FIELD_LIQUID_LIMIT_M3_PER_DAY
    assert (
        allocation.allocated_liquid_m3_per_day()
        <= FIELD_LIQUID_LIMIT_M3_PER_DAY + TOLERANCE_M3_PER_DAY
    )
