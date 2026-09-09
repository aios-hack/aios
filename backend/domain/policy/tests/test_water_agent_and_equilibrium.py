from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Rule,
    Schedule,
    ScheduleMeta,
    TraceEntry,
    WellState,
)

from backend.domain.policy import (
    Evaluation,
    FixedPointResult,
    Level,
    PolicyState,
    RuleContext,
    RuleFlags,
    RunTrace,
    default_theta,
    resolve,
    run_step,
)
from backend.domain.policy.agents import (
    DEFAULT_REGISTRY,
    WATER_AGENT,
    WATER_AGENT_RANK,
    WATER_CEILING_DECISION,
    WATER_REGISTRY,
    AgentRegistry,
    FieldCoordinator,
    GroupAllocator,
    Proposal,
    WaterAgent,
    WellExecutor,
    water_ceiling_for,
    with_agents,
)
from backend.domain.policy.agents.base import Bound, BoundSense, merge_proposals
from backend.domain.policy.agents.registry import rank_of
from backend.domain.policy.budget import injection_ceiling_for_well
from backend.domain.policy.fixed_point import PolicyEquilibrium, Visited
from backend.domain.policy.theta import (
    DEFAULT_THETA_REGISTRY,
    THETA_CAP,
    ThetaRegistry,
    ThetaSpec,
)
from backend.domain.policy.trace import dumps, loads, to_payload, trace_hash
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
WELL = "42"
UNKNOWN_FORMAT_TRACE = '{"format": "trace-0", "flags": {}, "entries": []}'


def two_group_state() -> PolicyState:
    return state_of(
        producer("p1", liquid_rate_m3_per_day=60.0, watercut=0.30, setpoint=60.0),
        producer("p2", liquid_rate_m3_per_day=50.0, watercut=0.95, setpoint=50.0),
        injector("i1", injection_rate_m3_per_day=150.0),
        injector("i2", injection_rate_m3_per_day=150.0),
    )


def two_group_context(context: RuleContext) -> RuleContext:
    return replace(
        context,
        influence=influence_of(
            producers=("p1", "p2"),
            injectors=("i1", "i2"),
            matrix=((0.5, 0.02), (0.02, 0.5)),
        ),
        groups=groups_of({GROUP_A: ("p1", "i1"), GROUP_B: ("p2", "i2")}),
        injection_budget_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
        group_injection_m3_per_day={GROUP_A: 150.0, GROUP_B: 150.0},
        group_offtake_m3_per_day={GROUP_A: 60.0, GROUP_B: 50.0},
        memory=memory_of(),
    )


def only_r1_flags() -> RuleFlags:
    return RuleFlags(enabled={rule: rule is Rule.R1 for rule in Rule})


@dataclass(frozen=True, slots=True)
class SilentWellAgent:
    name: str = "SilentWellAgent"
    level: Level = Level.WELL
    rank: int = 40
    responsibilities: tuple[str, ...] = (
        "не предлагает ничего и потому ничего не меняет",
    )

    def propose(self, state: PolicyState, context: RuleContext) -> Proposal:
        return Proposal(
            level=Level.WELL,
            agent=self.name,
            decisions=(),
            rule_by_decision=(),
            trace=(),
        )


def with_water(*extra) -> AgentRegistry:
    return AgentRegistry(
        agents=(
            FieldCoordinator(),
            WaterAgent(),
            GroupAllocator(),
            WellExecutor(),
        )
        + extra
    )


def without_water(*extra) -> AgentRegistry:
    return AgentRegistry(
        agents=(FieldCoordinator(), GroupAllocator(), WellExecutor()) + extra
    )


def full_trace(result) -> list[tuple[str, str, str, int, dict[str, float]]]:
    return [
        (
            leveled.level.value,
            leveled.agent,
            leveled.entry.decision,
            leveled.entry.control_step,
            dict(leveled.entry.inputs),
        )
        for leveled in result.trace.entries
    ]


def a_step(context: RuleContext, registry: AgentRegistry | None = None):
    kwargs = {} if registry is None else {"registry": registry}
    return run_step(
        two_group_state(),
        context,
        default_theta(),
        only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
        **kwargs,
    )


def test_water_agent_is_registered_and_ranked_after_the_field_coordinator() -> None:
    names = tuple(agent.name for agent in WATER_REGISTRY.by_level(Level.FIELD))
    assert names == ("FieldCoordinator", WATER_AGENT)
    coordinator = WATER_REGISTRY.of("FieldCoordinator")
    water = WATER_REGISTRY.of(WATER_AGENT)
    assert rank_of(water) == WATER_AGENT_RANK
    assert rank_of(water) > rank_of(coordinator)
    assert water.level is Level.FIELD
    assert water.responsibilities


def test_water_agent_is_called_after_the_field_coordinator_on_a_step(
    context: RuleContext,
) -> None:
    order = tuple(agent.name for agent in WATER_REGISTRY.call_order())
    assert order.index(WATER_AGENT) > order.index("FieldCoordinator")
    assert order.index(WATER_AGENT) < order.index("GroupAllocator")
    scoped = replace(
        two_group_context(context),
        injection_cap_m3_per_day={"i1": 40.0, "i2": 40.0},
    )
    result = a_step(scoped, WATER_REGISTRY)
    agents = [leveled.agent for leveled in result.trace.entries]
    assert WATER_AGENT in agents
    assert agents.index("field") < agents.index(WATER_AGENT)


def test_water_agent_joins_the_registry_by_one_line() -> None:
    extended = with_agents(DEFAULT_REGISTRY, WaterAgent())
    assert extended.names() == WATER_REGISTRY.names()
    assert extended.call_order()[1].name == WATER_AGENT


def test_two_water_agents_on_one_rank_are_refused() -> None:
    with pytest.raises(ValueError, match="заявили ранг"):
        with_agents(WATER_REGISTRY, WaterAgent(name="WaterAgentTwin"))


def test_registry_extension_without_an_agent_is_refused() -> None:
    with pytest.raises(ValueError, match="без единого агента"):
        with_agents(DEFAULT_REGISTRY)


def test_without_water_limits_the_step_is_bit_for_bit_the_same(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    assert scoped.injection_cap_m3_per_day == {}
    before = a_step(scoped)
    after = a_step(scoped, WATER_REGISTRY)
    assert after.decisions == before.decisions
    assert after.group_decisions == before.group_decisions
    assert after.allocation == before.allocation
    assert full_trace(after) == full_trace(before)
    assert trace_hash(after.trace.as_run_trace()) == trace_hash(
        before.trace.as_run_trace()
    )


def test_a_silent_water_agent_leaves_no_trace_entry(context: RuleContext) -> None:
    result = a_step(two_group_context(context), WATER_REGISTRY)
    assert not [
        leveled for leveled in result.trace.entries if leveled.agent == WATER_AGENT
    ]


def test_a_water_limit_puts_a_ceiling_into_the_trace_and_onto_the_setpoint(
    context: RuleContext,
) -> None:
    scoped = replace(
        two_group_context(context),
        injection_budget_m3_per_day=100.0,
        injection_cap_m3_per_day={"i1": 1000.0, "i2": 1000.0},
    )
    plain = a_step(scoped, without_water(SilentWellAgent()))
    capped = a_step(scoped, with_water(SilentWellAgent()))
    ceilings = [
        leveled for leveled in capped.trace.entries if leveled.agent == WATER_AGENT
    ]
    assert len(ceilings) == 2
    for leveled in ceilings:
        assert leveled.level is Level.FIELD
        assert leveled.entry.decision == WATER_CEILING_DECISION
        assert leveled.entry.inputs["water_ceiling_m3_per_day"] == 100.0

    before = {
        event.well: event.value
        for event in plain.decisions
        if event.kind is EventKind.SET_RATE
    }
    after = {
        event.well: event.value
        for event in capped.decisions
        if event.kind is EventKind.SET_RATE
    }
    assert set(after) == set(before)
    assert max(before.values()) > 100.0
    for well, value in after.items():
        assert value is not None
        assert value <= 100.0
        assert value <= before[well]


def test_a_generous_water_limit_never_raises_a_setpoint(
    context: RuleContext,
) -> None:
    scoped = replace(
        two_group_context(context),
        injection_cap_m3_per_day={"i1": 1e9, "i2": 1e9},
    )
    plain = a_step(scoped, without_water(SilentWellAgent()))
    generous = a_step(scoped, with_water(SilentWellAgent()))
    assert generous.decisions == plain.decisions


def test_the_water_agent_caps_injectors_only(context: RuleContext) -> None:
    scoped = replace(
        two_group_context(context),
        injection_cap_m3_per_day={"i1": 40.0, "p1": 5.0},
    )
    proposal = WaterAgent().propose(two_group_state(), scoped)
    assert tuple(bound.well for bound in proposal.bounds) == ("i1",)
    bound = proposal.bounds[0]
    assert bound.kind is EventKind.SET_RATE
    assert bound.sense is BoundSense.CEILING
    assert bound.value == 40.0


def test_the_tightest_of_the_two_water_sources_binds(context: RuleContext) -> None:
    scoped = replace(
        two_group_context(context),
        injection_budget_m3_per_day=80.0,
        injection_cap_m3_per_day={"i1": 500.0},
    )
    ceiling = water_ceiling_for(scoped, "i1")
    assert ceiling is not None
    assert ceiling.value_m3_per_day == 80.0
    tighter = water_ceiling_for(
        replace(scoped, injection_cap_m3_per_day={"i1": 20.0}), "i1"
    )
    assert tighter is not None
    assert tighter.value_m3_per_day == 20.0


def test_a_well_without_a_declared_water_cap_gets_no_ceiling(
    context: RuleContext,
) -> None:
    assert water_ceiling_for(two_group_context(context), "i1") is None


def test_a_negative_water_ceiling_is_reported_not_silently_zeroed() -> None:
    with pytest.raises(ValueError, match="отрицателен"):
        injection_ceiling_for_well(-1.0, None)
    with pytest.raises(ValueError, match="отрицателен"):
        injection_ceiling_for_well(None, -5.0)
    assert injection_ceiling_for_well(None, None) is None


def schedule_with(*values: float) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=(WELL,)),
        initial_state={
            WELL: WellState(
                availability=Availability.AVAILABLE,
                role=Role.PROD,
                operating_status=OperatingStatus.OPEN,
                setpoint=0.0,
            )
        },
        fixed_deck_events=(),
        control_events=tuple(
            ControlEvent(
                control_step=step,
                well=WELL,
                kind=EventKind.SET_LRAT,
                value=value,
            )
            for step, value in enumerate(values)
        ),
    )


def test_a_stationary_policy_leaves_every_step_quiet() -> None:
    def policy(state: object) -> Schedule:
        return schedule_with(1.0)

    def evaluator(schedule: Schedule) -> Evaluation:
        return Evaluation(npv=10.0, state=1.0)

    result = resolve(policy, evaluator, 1.0, 5)
    assert result.converged
    assert result.self_consistent
    assert result.iterations == 1
    assert result.quiet_steps() == 1
    assert result.quiet_step_fraction() == 1.0


def test_a_policy_that_moves_twice_then_settles_is_quiet_on_one_step_of_three() -> None:
    setpoints = (2.0, 3.0, 4.0, 4.0)
    seen = {"n": 0}

    def policy(state: object) -> Schedule:
        return schedule_with(setpoints[int(state)])

    def evaluator(schedule: Schedule) -> Evaluation:
        seen["n"] += 1
        return Evaluation(npv=float(seen["n"]), state=min(seen["n"], 3))

    result = resolve(policy, evaluator, 0, 8)
    assert result.iterations == 3
    assert result.converged
    assert result.quiet_steps() == 1
    assert result.quiet_step_fraction() == pytest.approx(1.0 / 3.0)
    assert result.as_equilibrium().observed_steps == 3


def test_a_policy_that_never_settles_is_quiet_on_no_step() -> None:
    seen = {"n": 0}

    def policy(state: object) -> Schedule:
        return schedule_with(float(state))

    def evaluator(schedule: Schedule) -> Evaluation:
        seen["n"] += 1
        return Evaluation(npv=float(seen["n"]), state=seen["n"])

    result = resolve(policy, evaluator, 0.0, 4)
    assert not result.converged
    assert result.quiet_steps() == 0
    assert result.quiet_step_fraction() == 0.0


def test_the_equilibrium_says_whether_the_policy_settled() -> None:
    def policy(state: object) -> Schedule:
        return schedule_with(7.0)

    def evaluator(schedule: Schedule) -> Evaluation:
        return Evaluation(npv=1.0, state=7.0)

    equilibrium = resolve(policy, evaluator, 7.0, 3).as_equilibrium()
    assert isinstance(equilibrium, PolicyEquilibrium)
    assert equilibrium.settled()
    assert equilibrium.as_dict() == {
        "iterations": 1,
        "converged": True,
        "self_consistent": True,
        "quiet_steps": 1,
        "observed_steps": 1,
        "quiet_step_fraction": 1.0,
        "settled": True,
    }


def test_an_unsettled_equilibrium_is_visible_as_such() -> None:
    seen = {"n": 0}

    def policy(state: object) -> Schedule:
        return schedule_with(float(state))

    def evaluator(schedule: Schedule) -> Evaluation:
        seen["n"] += 1
        return Evaluation(npv=float(seen["n"]), state=seen["n"])

    equilibrium = resolve(policy, evaluator, 0.0, 4).as_equilibrium()
    assert not equilibrium.settled()
    assert equilibrium.quiet_step_fraction() == 0.0
    assert equilibrium.observed_steps == 4


def test_an_equilibrium_without_an_observed_step_is_refused() -> None:
    with pytest.raises(ValueError, match="без единого наблюдённого шага"):
        PolicyEquilibrium(
            iterations=0,
            converged=False,
            self_consistent=False,
            quiet_steps=0,
            observed_steps=0,
        )


def test_more_quiet_steps_than_observed_is_refused() -> None:
    with pytest.raises(ValueError, match="доля вне"):
        PolicyEquilibrium(
            iterations=2,
            converged=False,
            self_consistent=False,
            quiet_steps=3,
            observed_steps=2,
        )


def test_a_visit_without_a_recorded_reaction_reports_an_error() -> None:
    visit = Visited(
        iteration=0,
        schedule=schedule_with(1.0),
        schedule_hash="a" * 64,
        npv=1.0,
    )
    with pytest.raises(ValueError, match="отклик политики не записан"):
        visit.is_quiet()


def test_a_result_built_without_reactions_reports_an_error_not_a_zero() -> None:
    schedule = schedule_with(1.0)
    result = FixedPointResult(
        schedule=schedule,
        schedule_hash="a" * 64,
        npv=5.0,
        converged=True,
        self_consistent=True,
        iterations=1,
        visited=(
            Visited(
                iteration=0,
                schedule=schedule,
                schedule_hash="a" * 64,
                npv=5.0,
            ),
        ),
    )
    with pytest.raises(ValueError, match="без записанного отклика"):
        result.quiet_steps()
    with pytest.raises(ValueError, match="без записанного отклика"):
        result.quiet_step_fraction()


def a_run_trace() -> RunTrace:
    flags = RuleFlags(enabled={rule: rule in (Rule.R1, Rule.R2) for rule in Rule})
    entries = (
        TraceEntry(
            control_step=0,
            well="i1",
            rule=Rule.R1,
            inputs={"water_ceiling_m3_per_day": 100.0, "binding_source": 2.0},
            decision=WATER_CEILING_DECISION,
        ),
        TraceEntry(
            control_step=3,
            well="p1",
            rule=Rule.R2,
            inputs={"watercut": 0.95},
            decision="SET_LRAT",
        ),
    )
    return RunTrace(entries=entries, flags=flags)


def test_a_run_trace_survives_a_json_round_trip_without_loss() -> None:
    trace = a_run_trace()
    restored = loads(dumps(trace))
    assert to_payload(restored) == to_payload(trace)
    assert trace_hash(restored) == trace_hash(trace)
    assert len(restored) == len(trace)
    assert restored.rules_fired() == trace.rules_fired()
    assert restored.wells() == trace.wells()
    assert restored.steps() == trace.steps()
    assert restored.count_by_rule() == trace.count_by_rule()
    assert restored.silent_rules() == trace.silent_rules()
    for before, after in zip(trace.entries, restored.entries):
        assert after.control_step == before.control_step
        assert after.well == before.well
        assert after.rule is before.rule
        assert after.decision == before.decision
        assert after.inputs == before.inputs


def test_a_trace_of_an_unknown_format_is_refused() -> None:
    with pytest.raises(ValueError, match="нераспознанный формат"):
        loads(UNKNOWN_FORMAT_TRACE)


def test_the_step_trace_of_a_water_capped_run_round_trips(
    context: RuleContext,
) -> None:
    scoped = replace(
        two_group_context(context),
        injection_budget_m3_per_day=100.0,
        injection_cap_m3_per_day={"i1": 1000.0, "i2": 1000.0},
    )
    trace = a_step(scoped, with_water(SilentWellAgent())).trace.as_run_trace()
    restored = loads(dumps(trace))
    assert trace_hash(restored) == trace_hash(trace)
    assert any(
        entry.decision == WATER_CEILING_DECISION for entry in restored.entries
    )


def test_the_theta_registry_holds_the_declared_set_and_its_own_cap() -> None:
    assert DEFAULT_THETA_REGISTRY.cap == THETA_CAP
    assert DEFAULT_THETA_REGISTRY.used() == THETA_CAP
    assert DEFAULT_THETA_REGISTRY.free() == 0
    assert set(DEFAULT_THETA_REGISTRY.names()) == set(
        DEFAULT_THETA_REGISTRY.defaults().values
    )


def test_a_new_parameter_needs_an_old_one_dropped_not_a_wider_contract() -> None:
    added = ThetaSpec("r4_water_margin", Rule.R4, 0.0, 1.0, 0.5)
    with pytest.raises(ValueError, match="параметров >"):
        DEFAULT_THETA_REGISTRY.extended_with((added,))
    swapped = DEFAULT_THETA_REGISTRY.without("r7_cycle_months").extended_with(
        (added,)
    )
    assert swapped.used() == THETA_CAP
    assert "r4_water_margin" in swapped.names()
    assert "r7_cycle_months" not in swapped.names()
    assert swapped.for_rule(Rule.R4) == (added,)
    assert set(swapped.defaults().values) == set(swapped.names())


def test_dropping_a_parameter_that_was_never_declared_is_refused() -> None:
    with pytest.raises(ValueError, match="незаявленные параметры"):
        DEFAULT_THETA_REGISTRY.without("r9_imaginary")


def test_the_same_parameter_twice_is_refused() -> None:
    spec = ThetaSpec("r4_probe", Rule.R4, 0.0, 1.0, 0.5)
    with pytest.raises(ValueError, match="объявлен дважды"):
        ThetaRegistry(specs=(spec, spec))


def test_a_non_positive_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="потолок"):
        ThetaRegistry(specs=(), cap=0)


def test_a_lone_proposal_still_honours_its_inherited_bounds() -> None:
    event = ControlEvent(
        control_step=0,
        well="i1",
        kind=EventKind.SET_RATE,
        value=900.0,
    )
    proposal = Proposal(
        level=Level.WELL,
        agent="executor",
        decisions=(event,),
        rule_by_decision=(Rule.R1,),
        trace=(),
        bounds=(
            Bound(
                well="i1",
                kind=EventKind.SET_RATE,
                sense=BoundSense.CEILING,
                value=100.0,
            ),
        ),
    )

    merged = merge_proposals((proposal,), 0, Rule.R1)

    assert merged.decisions[0].value == 100.0
