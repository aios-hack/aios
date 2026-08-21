from __future__ import annotations

from dataclasses import replace

import pytest

from aios_backend.core.contracts import (
    MAX_LRAT_M3_PER_DAY,
    Constraints,
    ControlEvent,
    EventKind,
    Role,
    Rule,
    WellOutage,
)

from aios_backend.domain.policy import (
    FIELD_AGENT,
    HierarchyTrace,
    Level,
    RuleContext,
    RuleFlags,
    allocate_field,
    decide_group,
    default_theta,
    execute_well,
    field_limit_from_constraints,
    group_demand_rub_per_m3,
    group_of,
    observations_by_group,
    restrict,
    rules_for_group,
    run_step,
    wells_without_group,
)
from aios_backend.domain.policy.tests.conftest import (
    groups_of,
    influence_of,
    injector,
    memory_of,
    producer,
    state_of,
)

FIELD_LIMIT_M3_PER_DAY = 600.0
GROUP_A = "G-A"
GROUP_B = "G-B"


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
        injection_budget_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
        group_injection_m3_per_day={GROUP_A: 150.0, GROUP_B: 150.0},
        group_offtake_m3_per_day={GROUP_A: 60.0, GROUP_B: 50.0},
        memory=memory_of(),
    )


def only_r1_flags() -> RuleFlags:
    return RuleFlags(
        enabled={rule: rule is Rule.R1 for rule in Rule}
    )


def test_field_manager_never_allocates_more_than_the_field_limit(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(
        two_group_state(), scoped, only_r1_flags(), FIELD_LIMIT_M3_PER_DAY
    )
    assert allocation.allocated_m3_per_day() <= FIELD_LIMIT_M3_PER_DAY + 1e-9
    assert len(allocation.limits) == len(scoped.groups.groups)


def test_field_shares_sum_to_one_when_any_group_has_positive_demand(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(
        two_group_state(), scoped, only_r1_flags(), FIELD_LIMIT_M3_PER_DAY
    )
    assert sum(limit.share_of_field for limit in allocation.limits) == pytest.approx(
        1.0
    )


def test_clean_group_gets_more_water_than_the_flooded_one(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(
        two_group_state(), scoped, only_r1_flags(), FIELD_LIMIT_M3_PER_DAY
    )
    assert (
        allocation.of(GROUP_A).injection_m3_per_day
        > allocation.of(GROUP_B).injection_m3_per_day
    )


def test_field_limit_of_zero_gives_every_group_zero(context: RuleContext) -> None:
    scoped = two_group_context(context)
    allocation = allocate_field(two_group_state(), scoped, only_r1_flags(), 0.0)
    assert allocation.allocated_m3_per_day() == 0.0


def test_field_manager_refuses_a_negative_limit(context: RuleContext) -> None:
    scoped = two_group_context(context)
    with pytest.raises(ValueError, match="отрицательный лимит поля"):
        allocate_field(two_group_state(), scoped, only_r1_flags(), -1.0)


def test_field_manager_refuses_to_work_without_groups(context: RuleContext) -> None:
    scoped = replace(two_group_context(context), groups=None)
    with pytest.raises(ValueError, match="без Groups"):
        allocate_field(
            two_group_state(), scoped, only_r1_flags(), FIELD_LIMIT_M3_PER_DAY
        )


def test_field_manager_refuses_to_work_without_a_limit(context: RuleContext) -> None:
    scoped = replace(two_group_context(context), injection_budget_m3_per_day=None)
    with pytest.raises(ValueError, match="лимит поля не задан"):
        allocate_field(two_group_state(), scoped, only_r1_flags())


def test_field_manager_has_no_formula_of_its_own_when_r1_is_off(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    flags = RuleFlags(enabled={rule: False for rule in Rule})
    with pytest.raises(ValueError, match="менеджер месторождения своей формулы"):
        allocate_field(
            two_group_state(), scoped, flags, FIELD_LIMIT_M3_PER_DAY
        )


def test_field_manager_refuses_to_split_without_lambda(context: RuleContext) -> None:
    scoped = replace(two_group_context(context), influence=None)
    with pytest.raises(ValueError, match="требует измеренную λ"):
        allocate_field(
            two_group_state(), scoped, only_r1_flags(), FIELD_LIMIT_M3_PER_DAY
        )


def test_group_agent_stays_within_its_own_limit(context: RuleContext) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    flags = only_r1_flags()
    allocation = allocate_field(state, scoped, flags, FIELD_LIMIT_M3_PER_DAY)
    theta = default_theta()
    for limit in allocation.limits:
        decision = decide_group(state, scoped, theta, flags, limit)
        assert (
            decision.requested_injection_m3_per_day
            <= limit.injection_m3_per_day + 1e-9
        )


def test_group_agent_sees_only_its_own_wells(context: RuleContext) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    inside = restrict(state, scoped.groups.groups[GROUP_A])
    assert set(inside.wells) == {"p1", "i1"}


def test_group_agent_delegates_to_rules_not_to_its_own_arithmetic(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    flags = only_r1_flags()
    allocation = allocate_field(state, scoped, flags, FIELD_LIMIT_M3_PER_DAY)
    decision = decide_group(
        state, scoped, default_theta(), flags, allocation.of(GROUP_A)
    )
    assert decision.rule_by_decision
    assert set(decision.rule_by_decision) <= set(rules_for_group(flags))
    assert all(
        leveled.entry.rule in set(rules_for_group(flags))
        for leveled in decision.trace
    )


def test_group_agent_produces_nothing_when_every_rule_is_off(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    flags = only_r1_flags()
    allocation = allocate_field(state, scoped, flags, FIELD_LIMIT_M3_PER_DAY)
    all_off_flags = RuleFlags(enabled={rule: False for rule in Rule})
    decision = decide_group(
        state, scoped, default_theta(), all_off_flags, allocation.of(GROUP_A)
    )
    assert decision.decisions == ()
    assert decision.trace == ()


def test_group_agent_scales_down_a_request_above_its_limit(
    context: RuleContext,
) -> None:
    from aios_backend.domain.policy.hierarchy import GroupLimit

    state = state_of(
        producer("p1", liquid_rate_m3_per_day=60.0, watercut=0.30, setpoint=60.0),
        injector("i1", injection_rate_m3_per_day=150.0),
        injector("i9", injection_rate_m3_per_day=400.0),
    )
    influence = influence_of(
        producers=("p1",), injectors=("i1",), matrix=((0.5,),)
    )
    scoped = replace(
        context,
        influence=influence,
        groups=groups_of({GROUP_A: ("p1", "i1", "i9")}),
        group_injection_m3_per_day={GROUP_A: 550.0},
        group_offtake_m3_per_day={GROUP_A: 60.0},
        memory=memory_of(),
        # i9 вне окна λ и держит базовую уставку: ценность её закачки
        # неизвестна, но обнулять скважину из-за отсутствия замера нельзя.
        # Именно этот удержанный уровень и делает запрос участка выше лимита,
        # то есть проверяет ровно то, ради чего тест написан.
        baseline_injection_m3_per_day={"i9": 400.0},
    )
    flags = only_r1_flags()
    limit = GroupLimit(
        group_id=GROUP_A,
        injection_m3_per_day=200.0,
        share_of_field=1.0,
        demand_rub_per_m3=1.0,
    )
    decision = decide_group(state, scoped, default_theta(), flags, limit)
    assert (
        decision.requested_injection_m3_per_day
        <= limit.injection_m3_per_day + 1e-9
    )
    scaled = [
        leveled
        for leveled in decision.trace
        if leveled.entry.decision == "SCALE_TO_GROUP_LIMIT"
    ]
    assert len(scaled) == 1
    assert scaled[0].entry.inputs["group_limit_scale"] < 1.0


def test_group_limit_rejects_a_request_it_cannot_satisfy(
    context: RuleContext,
) -> None:
    from aios_backend.domain.policy.hierarchy import GroupDecision, GroupLimit

    limit = GroupLimit(
        group_id=GROUP_A,
        injection_m3_per_day=10.0,
        share_of_field=0.5,
        demand_rub_per_m3=1.0,
    )
    with pytest.raises(ValueError, match="запросил"):
        GroupDecision(
            group_id=GROUP_A,
            limit=limit,
            decisions=(),
            rule_by_decision=(),
            trace=(),
            requested_injection_m3_per_day=11.0,
        )


def test_executor_quantizes_the_setpoint(context: RuleContext) -> None:
    state = two_group_state()
    event = ControlEvent(
        control_step=0, well="i1", kind=EventKind.SET_RATE, value=137.0
    )
    applied, leveled = execute_well(
        state, context, event, Rule.R1, agent="i1", setpoint_step_m3_per_day=25.0
    )
    assert applied is not None
    assert applied.value == pytest.approx(125.0)
    assert leveled.level is Level.WELL
    assert leveled.entry.inputs["setpoint_step_m3_per_day"] == 25.0


def test_executor_holds_the_lrat_ceiling(context: RuleContext) -> None:
    state = two_group_state()
    event = ControlEvent(
        control_step=0,
        well="p1",
        kind=EventKind.SET_LRAT,
        value=MAX_LRAT_M3_PER_DAY,
    )
    applied, leveled = execute_well(
        state,
        context,
        event,
        Rule.R2,
        agent="p1",
        setpoint_step_m3_per_day=MAX_LRAT_M3_PER_DAY / 2.0,
    )
    assert applied is not None
    assert applied.value <= MAX_LRAT_M3_PER_DAY
    assert leveled.entry.inputs["lrat_ceiling_m3_per_day"] == MAX_LRAT_M3_PER_DAY


def test_executor_vetoes_a_decision_inside_an_outage(context: RuleContext) -> None:
    scoped = replace(
        context,
        constraints=Constraints(
            well_outages=(
                WellOutage(well="i1", control_step_from=0, control_step_to=5),
            )
        ),
    )
    state = two_group_state()
    event = ControlEvent(
        control_step=3, well="i1", kind=EventKind.SET_RATE, value=100.0
    )
    applied, leveled = execute_well(state, scoped, event, Rule.R1, agent="i1")
    assert applied is None
    assert leveled.entry.decision == "VETO_OUTAGE"


def test_executor_lets_a_decision_outside_the_outage_through(
    context: RuleContext,
) -> None:
    scoped = replace(
        context,
        constraints=Constraints(
            well_outages=(
                WellOutage(well="i1", control_step_from=0, control_step_to=5),
            )
        ),
    )
    state = two_group_state()
    event = ControlEvent(
        control_step=6, well="i1", kind=EventKind.SET_RATE, value=100.0
    )
    applied, _ = execute_well(state, scoped, event, Rule.R1, agent="i1")
    assert applied is not None


def test_executor_refuses_a_well_it_cannot_see(context: RuleContext) -> None:
    state = two_group_state()
    event = ControlEvent(
        control_step=0, well="ghost", kind=EventKind.SET_RATE, value=1.0
    )
    with pytest.raises(ValueError, match="не видит состояния скважины"):
        execute_well(state, context, event, Rule.R1, agent="ghost")


def test_executor_refuses_a_non_positive_quantization_step(
    context: RuleContext,
) -> None:
    state = two_group_state()
    event = ControlEvent(
        control_step=0, well="i1", kind=EventKind.SET_RATE, value=10.0
    )
    with pytest.raises(ValueError, match="шаг квантования"):
        execute_well(
            state, context, event, Rule.R1, agent="i1", setpoint_step_m3_per_day=0.0
        )


def test_run_step_never_injects_more_than_the_field_limit(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    result = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    assert result.injected_m3_per_day() <= FIELD_LIMIT_M3_PER_DAY + 1e-9


def test_run_step_collects_trace_from_all_three_levels(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    result = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    assert result.trace.levels_present() == (Level.FIELD, Level.GROUP, Level.WELL)
    counted = result.trace.count_by_level()
    assert counted[Level.FIELD] == len(scoped.groups.groups)
    assert counted[Level.GROUP] > 0
    assert counted[Level.WELL] > 0


def test_every_trace_entry_names_its_level_and_agent(context: RuleContext) -> None:
    scoped = two_group_context(context)
    result = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    for leveled in result.trace.entries:
        assert leveled.level in set(Level)
        assert leveled.agent
        assert leveled.entry.inputs
    assert {e.agent for e in result.trace.by_level(Level.FIELD)} == {FIELD_AGENT}
    assert {e.agent for e in result.trace.by_level(Level.GROUP)} == set(
        scoped.groups.groups
    )


def test_hierarchy_trace_flattens_into_the_run_trace_of_task_23(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    flags = only_r1_flags()
    result = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        flags,
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    flat = result.trace.as_run_trace()
    assert len(flat) == len(result.trace)
    assert flat.by_rule(Rule.R1)


def test_a_rule_switched_off_cannot_leave_a_record_at_any_level(
    context: RuleContext,
) -> None:
    from aios_backend.domain.policy.hierarchy import LeveledTraceEntry
    from aios_backend.core.contracts import TraceEntry

    flags = only_r1_flags()
    entry = LeveledTraceEntry(
        level=Level.WELL,
        agent="p1",
        entry=TraceEntry(
            control_step=0,
            well="p1",
            rule=Rule.R7,
            inputs={"x": 1.0},
            decision="SHUT",
        ),
    )
    with pytest.raises(ValueError, match="выключено флагом"):
        HierarchyTrace(entries=(entry,), flags=flags)


def test_leveled_entry_without_numbers_is_refused() -> None:
    from aios_backend.domain.policy.hierarchy import LeveledTraceEntry
    from aios_backend.core.contracts import TraceEntry

    with pytest.raises(ValueError, match="без чисел входа"):
        LeveledTraceEntry(
            level=Level.FIELD,
            agent=FIELD_AGENT,
            entry=TraceEntry(
                control_step=0,
                well=GROUP_A,
                rule=Rule.R1,
                inputs={},
                decision="SET_GROUP_LIMIT",
            ),
        )


def test_run_step_is_deterministic(context: RuleContext) -> None:
    scoped = two_group_context(context)
    first = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    second = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    assert first.decisions == second.decisions
    assert [e.entry for e in first.trace.entries] == [
        e.entry for e in second.trace.entries
    ]


def test_sum_of_group_injection_never_exceeds_the_field_limit_with_all_rules_on(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    flags = RuleFlags()
    result = run_step(
        state,
        scoped,
        default_theta(),
        flags,
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    per_group = {
        decision.group_id: decision.requested_injection_m3_per_day
        for decision in result.group_decisions
    }
    for decision in result.group_decisions:
        assert (
            per_group[decision.group_id]
            <= decision.limit.injection_m3_per_day + 1e-9
        )
    assert sum(per_group.values()) <= FIELD_LIMIT_M3_PER_DAY + 1e-9
    assert result.trace.levels_present() == (Level.FIELD, Level.GROUP, Level.WELL)


def test_a_tighter_field_limit_never_raises_the_water_that_goes_out(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    flags = only_r1_flags()
    wide = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        flags,
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    narrow = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        flags,
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY / 4.0,
    )
    assert narrow.injected_m3_per_day() <= wide.injected_m3_per_day() + 1e-9
    assert narrow.injected_m3_per_day() <= FIELD_LIMIT_M3_PER_DAY / 4.0 + 1e-9


def test_the_executor_layer_can_only_lower_what_the_group_asked(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    result = run_step(
        two_group_state(),
        scoped,
        default_theta(),
        only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
        setpoint_step_m3_per_day=None,
    )
    asked = {
        event.well: event.value
        for decision in result.group_decisions
        for event in decision.decisions
        if event.kind is EventKind.SET_RATE and event.value is not None
    }
    applied = {
        event.well: event.value
        for event in result.decisions
        if event.kind is EventKind.SET_RATE and event.value is not None
    }
    for well, value in applied.items():
        assert value <= asked[well] + 1e-9


def test_field_limit_comes_from_constraints_not_from_the_manager(
    context: RuleContext,
) -> None:
    year = 2010
    scoped = replace(
        context,
        constraints=Constraints(injection_limits={year: FIELD_LIMIT_M3_PER_DAY}),
    )
    assert field_limit_from_constraints(scoped, year) == FIELD_LIMIT_M3_PER_DAY
    with pytest.raises(ValueError, match="не назначает доступную воду сам"):
        field_limit_from_constraints(scoped, year + 1)


def test_group_of_reports_every_group_a_well_belongs_to(
    context: RuleContext,
) -> None:
    groups = groups_of({GROUP_A: ("p1", "i1"), GROUP_B: ("p1", "i2")})
    assert group_of(groups, "p1") == (GROUP_A, GROUP_B)
    assert group_of(groups, "p2") == ()


def test_wells_without_group_are_named(context: RuleContext) -> None:
    groups = groups_of({GROUP_A: ("p1", "i1")})
    assert wells_without_group(groups, ("p1", "p2", "i1", "i2")) == ("i2", "p2")


def test_group_demand_counts_only_open_injectors_inside_lambda(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    demand, counted = group_demand_rub_per_m3(
        state, scoped, scoped.groups.groups[GROUP_A]
    )
    assert counted == 1
    assert demand > 0.0


def test_observations_by_group_keeps_group_membership(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    collected = observations_by_group(state, scoped.groups)
    assert set(collected) == {GROUP_A, GROUP_B}
    assert {obs.well for obs in collected[GROUP_A]} == {"p1", "i1"}
    assert all(
        obs.role in (Role.PROD, Role.INJ) for obs in collected[GROUP_B]
    )
