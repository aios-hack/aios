from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core.contracts import ControlEvent, EventKind, Rule

from backend.domain.policy import (
    FIELD_AGENT,
    Level,
    RuleContext,
    RuleFlags,
    default_theta,
    run_step,
)
from backend.domain.policy.agents import (
    DEFAULT_AGENTS,
    DEFAULT_REGISTRY,
    LEVEL_ORDER,
    Agent,
    AgentRegistry,
    FieldCoordinator,
    GroupAllocator,
    Proposal,
    WellExecutor,
)
from backend.domain.policy.tests.conftest import (
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
    return RuleFlags(enabled={rule: rule is Rule.R1 for rule in Rule})


def test_registry_holds_the_three_agents_of_the_hierarchy() -> None:
    assert DEFAULT_REGISTRY.names() == (
        "FieldCoordinator",
        "GroupAllocator",
        "WellExecutor",
    )
    assert len(DEFAULT_AGENTS) == len(DEFAULT_REGISTRY.agents)


def test_every_agent_name_is_unique() -> None:
    names = DEFAULT_REGISTRY.names()
    assert len(set(names)) == len(names)


def test_a_duplicate_name_is_refused() -> None:
    with pytest.raises(ValueError, match="встречается дважды"):
        AgentRegistry(agents=(FieldCoordinator(), FieldCoordinator()))


def test_an_empty_registry_is_refused() -> None:
    with pytest.raises(ValueError, match="реестр агентов пуст"):
        AgentRegistry(agents=())


def test_every_level_of_the_hierarchy_has_exactly_one_agent() -> None:
    for level in LEVEL_ORDER:
        assert len(DEFAULT_REGISTRY.by_level(level)) == 1
        assert DEFAULT_REGISTRY.one_of_level(level).level is level


def test_agent_levels_match_the_classes_they_come_from() -> None:
    assert DEFAULT_REGISTRY.of("FieldCoordinator").level is Level.FIELD
    assert DEFAULT_REGISTRY.of("GroupAllocator").level is Level.GROUP
    assert DEFAULT_REGISTRY.of("WellExecutor").level is Level.WELL


def test_every_agent_states_what_it_is_responsible_for() -> None:
    for agent in DEFAULT_REGISTRY.agents:
        assert agent.responsibilities
        assert all(text.strip() for text in agent.responsibilities)


def test_an_agent_without_responsibilities_is_refused() -> None:
    mute = replace(FieldCoordinator(), responsibilities=())
    with pytest.raises(ValueError, match="без описанной ответственности"):
        AgentRegistry(agents=(mute,))


def test_call_order_on_a_step_goes_field_then_group_then_well() -> None:
    assert tuple(
        agent.level for agent in DEFAULT_REGISTRY.call_order()
    ) == LEVEL_ORDER


def test_registry_refuses_a_name_it_does_not_hold() -> None:
    with pytest.raises(ValueError, match="нет в реестре"):
        DEFAULT_REGISTRY.of("PressureAgent")


def test_the_three_agents_satisfy_the_agent_protocol() -> None:
    for agent in (FieldCoordinator(), GroupAllocator(), WellExecutor()):
        assert isinstance(agent, Agent)


def test_run_step_takes_agent_names_for_the_trace_from_the_registry(
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
    coordinator = DEFAULT_REGISTRY.one_of_level(Level.FIELD)
    assert coordinator.trace_agent == FIELD_AGENT
    assert {e.agent for e in result.trace.by_level(Level.FIELD)} == {
        coordinator.trace_agent
    }
    assert {e.agent for e in result.trace.by_level(Level.GROUP)} == set(
        scoped.groups.groups
    )


def test_an_explicit_registry_gives_the_same_step_as_the_default(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    theta = default_theta()
    flags = only_r1_flags()
    default = run_step(
        two_group_state(),
        scoped,
        theta,
        flags,
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    explicit = run_step(
        two_group_state(),
        scoped,
        theta,
        flags,
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
        registry=AgentRegistry(
            agents=(FieldCoordinator(), GroupAllocator(), WellExecutor())
        ),
    )
    assert default.decisions == explicit.decisions
    assert [e.entry for e in default.trace.entries] == [
        e.entry for e in explicit.trace.entries
    ]
    assert [e.agent for e in default.trace.entries] == [
        e.agent for e in explicit.trace.entries
    ]


def test_a_proposal_without_an_author_is_refused() -> None:
    with pytest.raises(ValueError, match="без имени агента"):
        Proposal(
            level=Level.WELL,
            agent="",
            decisions=(),
            rule_by_decision=(),
            trace=(),
        )


def test_a_proposal_that_loses_the_rule_behind_a_decision_is_refused() -> None:
    event = ControlEvent(
        control_step=0, well="i1", kind=EventKind.SET_RATE, value=10.0
    )
    with pytest.raises(ValueError, match="не восстановимо"):
        Proposal(
            level=Level.WELL,
            agent="i1",
            decisions=(event,),
            rule_by_decision=(),
            trace=(),
        )


def test_the_field_coordinator_proposes_quotas_not_setpoints(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    proposal = DEFAULT_REGISTRY.of("FieldCoordinator").propose(
        two_group_state(),
        scoped,
        flags=only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
    )
    assert proposal.level is Level.FIELD
    assert proposal.decisions == ()
    assert proposal.trace
    assert all(e.entry.decision == "SET_GROUP_LIMIT" for e in proposal.trace)


def test_the_group_allocator_proposes_inside_its_quota(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    state = two_group_state()
    flags = only_r1_flags()
    coordinator = DEFAULT_REGISTRY.of("FieldCoordinator")
    allocation = coordinator.allocate(
        state, scoped, flags, FIELD_LIMIT_M3_PER_DAY
    )
    proposal = DEFAULT_REGISTRY.of("GroupAllocator").propose(
        state,
        scoped,
        theta=default_theta(),
        flags=flags,
        limit=allocation.of(GROUP_A),
    )
    assert proposal.level is Level.GROUP
    assert proposal.agent == GROUP_A
    assert len(proposal.decisions) == len(proposal.rule_by_decision)


def test_the_well_executor_does_not_invent_a_decision(
    context: RuleContext,
) -> None:
    with pytest.raises(ValueError, match="не изобретает решений"):
        DEFAULT_REGISTRY.of("WellExecutor").propose(two_group_state(), context)


def test_the_field_coordinator_has_no_rules_of_its_own(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    with pytest.raises(ValueError, match="без RuleFlags"):
        DEFAULT_REGISTRY.of("FieldCoordinator").propose(two_group_state(), scoped)
