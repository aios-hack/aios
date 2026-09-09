from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from backend.core.contracts import ControlEvent, EventKind, Rule, TraceEntry

from backend.domain.policy import (
    Level,
    LeveledTraceEntry,
    PolicyState,
    RuleContext,
    RuleFlags,
    default_theta,
    run_step,
)
from backend.domain.policy.agents import (
    DEFAULT_REGISTRY,
    AgentRegistry,
    FieldCoordinator,
    GroupAllocator,
    Proposal,
    WellExecutor,
)
from backend.domain.policy.agents.base import (
    Bound,
    BoundSense,
    Verdict,
    merge_bounds,
    merge_proposals,
)
from backend.domain.policy.agents.registry import rank_of
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


def two_group_state() -> PolicyState:
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


def a_trace_entry(well: str, decision: str) -> LeveledTraceEntry:
    return LeveledTraceEntry(
        level=Level.WELL,
        agent=well,
        entry=TraceEntry(
            control_step=0,
            well=well,
            rule=Rule.R1,
            inputs={"probe": 1.0},
            decision=decision,
        ),
    )


@dataclass(frozen=True, slots=True)
class RecordingWellAgent:
    calls: list[str]
    name: str = "RecordingWellAgent"
    level: Level = Level.WELL
    rank: int = 10
    responsibilities: tuple[str, ...] = (
        "записывает факт своего вызова, чтобы расширение реестра было проверяемо",
    )

    def propose(self, state: PolicyState, context: RuleContext) -> Proposal:
        self.calls.append(f"step={state.control_step}")
        return Proposal(
            level=Level.WELL,
            agent=self.name,
            decisions=(),
            rule_by_decision=(),
            trace=(a_trace_entry(self.name, "OBSERVED"),),
        )


@dataclass(frozen=True, slots=True)
class InjectionCapAgent:
    cap_m3_per_day: float
    wells: tuple[str, ...]
    name: str = "InjectionCapAgent"
    level: Level = Level.WELL
    rank: int = 20
    responsibilities: tuple[str, ...] = (
        "держит потолок закачки на скважину и не поднимает чужой потолок",
    )

    def propose(self, state: PolicyState, context: RuleContext) -> Proposal:
        return Proposal(
            level=Level.WELL,
            agent=self.name,
            decisions=(),
            rule_by_decision=(),
            trace=(),
            bounds=tuple(
                Bound(
                    well=well,
                    kind=EventKind.SET_RATE,
                    sense=BoundSense.CEILING,
                    value=self.cap_m3_per_day,
                )
                for well in self.wells
            ),
        )


@dataclass(frozen=True, slots=True)
class VetoWellAgent:
    reason: str = "MAINTENANCE"
    name: str = "VetoWellAgent"
    level: Level = Level.WELL
    rank: int = 30
    responsibilities: tuple[str, ...] = (
        "запрещает исполнение решения целиком, а не обнуляет уставку",
    )

    def propose(self, state: PolicyState, context: RuleContext) -> Proposal:
        return Proposal(
            level=Level.WELL,
            agent=self.name,
            decisions=(),
            rule_by_decision=(),
            trace=(),
            verdict=Verdict.VETO,
            veto_reason=self.reason,
        )


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
    scoped = two_group_context(context)
    kwargs = {} if registry is None else {"registry": registry}
    return run_step(
        two_group_state(),
        scoped,
        default_theta(),
        only_r1_flags(),
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
        **kwargs,
    )


def test_one_agent_per_level_keeps_the_step_bit_for_bit(
    context: RuleContext,
) -> None:
    default = a_step(context)
    explicit = a_step(
        context,
        AgentRegistry(agents=(FieldCoordinator(), GroupAllocator(), WellExecutor())),
    )
    assert default.decisions == explicit.decisions
    assert full_trace(default) == full_trace(explicit)
    assert default.group_decisions == explicit.group_decisions
    assert default.allocation == explicit.allocation
    assert len(default.trace) == len(explicit.trace)


def test_a_silent_second_agent_does_not_move_a_single_number(
    context: RuleContext,
) -> None:
    before = a_step(context)
    after = a_step(
        context,
        AgentRegistry(
            agents=(
                FieldCoordinator(),
                GroupAllocator(),
                WellExecutor(),
                SilentWellAgent(),
            )
        ),
    )
    assert after.decisions == before.decisions
    assert after.group_decisions == before.group_decisions
    assert full_trace(after) == full_trace(before)


def test_a_second_agent_joins_a_level_without_touching_the_core(
    context: RuleContext,
) -> None:
    calls: list[str] = []
    registry = AgentRegistry(
        agents=(
            FieldCoordinator(),
            GroupAllocator(),
            WellExecutor(),
            RecordingWellAgent(calls=calls),
        )
    )
    assert len(registry.by_level(Level.WELL)) == 2
    result = a_step(context, registry)
    assert calls
    assert any(
        leveled.agent == "RecordingWellAgent" and leveled.entry.decision == "OBSERVED"
        for leveled in result.trace.entries
    )


def test_by_level_orders_agents_by_declared_rank_not_by_registration(
    context: RuleContext,
) -> None:
    executor = WellExecutor()
    late = SilentWellAgent(name="Zzz", rank=5)
    early = RecordingWellAgent(calls=[], name="Aaa", rank=1)
    forward = AgentRegistry(
        agents=(FieldCoordinator(), GroupAllocator(), executor, late, early)
    )
    backward = AgentRegistry(
        agents=(early, late, executor, GroupAllocator(), FieldCoordinator())
    )
    assert forward.by_level(Level.WELL) == backward.by_level(Level.WELL)
    assert tuple(
        agent.name for agent in forward.by_level(Level.WELL)
    ) == ("WellExecutor", "Aaa", "Zzz")
    assert tuple(agent.name for agent in forward.call_order()) == (
        "FieldCoordinator",
        "GroupAllocator",
        "WellExecutor",
        "Aaa",
        "Zzz",
    )


def test_two_agents_claiming_one_rank_on_one_level_are_refused() -> None:
    with pytest.raises(ValueError, match="заявили ранг"):
        AgentRegistry(
            agents=(
                FieldCoordinator(),
                GroupAllocator(),
                WellExecutor(),
                SilentWellAgent(name="A", rank=7),
                SilentWellAgent(name="B", rank=7),
            )
        )


def test_a_default_agent_without_a_rank_field_sits_at_rank_zero() -> None:
    assert rank_of(WellExecutor()) == 0
    assert rank_of(FieldCoordinator()) == 0
    for level in (Level.FIELD, Level.GROUP, Level.WELL):
        assert len(DEFAULT_REGISTRY.by_level(level)) == 1


def test_a_non_integer_rank_is_refused() -> None:
    with pytest.raises(ValueError, match="не целое"):
        rank_of(SilentWellAgent(rank="first"))  # type: ignore[arg-type]


def test_a_ceiling_is_restricted_by_the_smaller_of_the_two() -> None:
    standing = Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 200.0)
    tighter = Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 120.0)
    looser = Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 900.0)
    assert standing.tightened_by(tighter) is tighter
    assert standing.tightened_by(looser) is standing


def test_a_floor_is_restricted_by_the_larger_of_the_two() -> None:
    standing = Bound("p1", EventKind.SET_LRAT, BoundSense.FLOOR, 20.0)
    tighter = Bound("p1", EventKind.SET_LRAT, BoundSense.FLOOR, 35.0)
    looser = Bound("p1", EventKind.SET_LRAT, BoundSense.FLOOR, 5.0)
    assert standing.tightened_by(tighter) is tighter
    assert standing.tightened_by(looser) is standing


def test_a_bound_never_compares_against_a_different_quantity() -> None:
    ceiling = Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 100.0)
    floor = Bound("i1", EventKind.SET_RATE, BoundSense.FLOOR, 100.0)
    with pytest.raises(ValueError, match="границы разных величин"):
        ceiling.tightened_by(floor)


def test_merge_of_a_ceiling_and_a_floor_keeps_both() -> None:
    merged, tightened = merge_bounds(
        (Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 100.0),),
        (Bound("i1", EventKind.SET_RATE, BoundSense.FLOOR, 10.0),),
    )
    assert len(merged) == 2
    assert tightened == ()


def test_a_later_agent_only_narrows_a_standing_bound() -> None:
    merged, tightened = merge_bounds(
        (
            Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 100.0),
            Bound("p1", EventKind.SET_LRAT, BoundSense.FLOOR, 20.0),
        ),
        (
            Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 500.0),
            Bound("p1", EventKind.SET_LRAT, BoundSense.FLOOR, 45.0),
        ),
    )
    by_key = {bound.key(): bound.value for bound in merged}
    assert by_key[("i1", "SET_RATE", "CEILING")] == 100.0
    assert by_key[("p1", "SET_LRAT", "FLOOR")] == 45.0
    assert len(tightened) == 1


def test_merged_bounds_do_not_depend_on_the_order_of_two_restrictors() -> None:
    a = Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 80.0)
    b = Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 40.0)
    first, _ = merge_bounds((a,), (b,))
    second, _ = merge_bounds((b,), (a,))
    assert first == second
    assert first[0].value == 40.0


def test_a_veto_is_not_a_zero_setpoint() -> None:
    zero = Proposal(
        level=Level.WELL,
        agent="i1",
        decisions=(
            ControlEvent(control_step=0, well="i1", kind=EventKind.SET_RATE, value=0.0),
        ),
        rule_by_decision=(Rule.R1,),
        trace=(),
    )
    veto = Proposal(
        level=Level.WELL,
        agent="i1",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        verdict=Verdict.VETO,
        veto_reason="OUTAGE",
    )
    assert zero.verdict is Verdict.ALLOW
    assert zero.decisions[0].value == 0.0
    assert veto.verdict is Verdict.VETO
    assert veto.decisions == ()
    assert zero != veto


def test_a_veto_may_not_carry_a_decision() -> None:
    with pytest.raises(ValueError, match="вето с 1 решениями"):
        Proposal(
            level=Level.WELL,
            agent="i1",
            decisions=(
                ControlEvent(
                    control_step=0, well="i1", kind=EventKind.SET_RATE, value=5.0
                ),
            ),
            rule_by_decision=(Rule.R1,),
            trace=(),
            verdict=Verdict.VETO,
            veto_reason="OUTAGE",
        )


def test_a_veto_without_a_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="вето без причины"):
        Proposal(
            level=Level.WELL,
            agent="i1",
            decisions=(),
            rule_by_decision=(),
            trace=(),
            verdict=Verdict.VETO,
        )


def test_a_reason_without_a_veto_is_refused() -> None:
    with pytest.raises(ValueError, match="причина вето при вердикте"):
        Proposal(
            level=Level.WELL,
            agent="i1",
            decisions=(),
            rule_by_decision=(),
            trace=(),
            veto_reason="OUTAGE",
        )


def test_the_same_bound_declared_twice_is_refused() -> None:
    bound = Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 10.0)
    with pytest.raises(ValueError, match="объявлена дважды"):
        Proposal(
            level=Level.WELL,
            agent="i1",
            decisions=(),
            rule_by_decision=(),
            trace=(),
            bounds=(bound, replace(bound, value=20.0)),
        )


def test_a_veto_beats_a_bound_no_matter_which_agent_spoke_first() -> None:
    event = ControlEvent(
        control_step=0, well="i1", kind=EventKind.SET_RATE, value=150.0
    )
    primary = Proposal(
        level=Level.WELL,
        agent="i1",
        decisions=(event,),
        rule_by_decision=(Rule.R1,),
        trace=(),
    )
    capper = Proposal(
        level=Level.WELL,
        agent="cap",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        bounds=(Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 50.0),),
    )
    vetoer = Proposal(
        level=Level.WELL,
        agent="veto",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        verdict=Verdict.VETO,
        veto_reason="OUTAGE",
    )
    cap_then_veto = merge_proposals((primary, capper, vetoer), 0)
    veto_then_cap = merge_proposals((primary, vetoer, capper), 0)
    assert cap_then_veto.verdict is Verdict.VETO
    assert veto_then_cap.verdict is Verdict.VETO
    assert cap_then_veto.decisions == ()
    assert veto_then_cap.decisions == ()
    assert cap_then_veto.bounds == veto_then_cap.bounds


def test_merging_clamps_a_decision_to_the_tightest_ceiling() -> None:
    event = ControlEvent(
        control_step=0, well="i1", kind=EventKind.SET_RATE, value=150.0
    )
    primary = Proposal(
        level=Level.WELL,
        agent="i1",
        decisions=(event,),
        rule_by_decision=(Rule.R1,),
        trace=(),
    )
    loose = Proposal(
        level=Level.WELL,
        agent="loose",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        bounds=(Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 120.0),),
    )
    tight = Proposal(
        level=Level.WELL,
        agent="tight",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        bounds=(Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 60.0),),
    )
    merged = merge_proposals((primary, loose, tight), 0)
    assert merged.decisions[0].value == 60.0
    assert merged.rule_by_decision == (Rule.R1,)


def test_merging_lifts_a_decision_to_the_highest_floor() -> None:
    event = ControlEvent(
        control_step=0, well="p1", kind=EventKind.SET_LRAT, value=10.0
    )
    primary = Proposal(
        level=Level.WELL,
        agent="p1",
        decisions=(event,),
        rule_by_decision=(Rule.R2,),
        trace=(),
    )
    low = Proposal(
        level=Level.WELL,
        agent="low",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        bounds=(Bound("p1", EventKind.SET_LRAT, BoundSense.FLOOR, 25.0),),
    )
    high = Proposal(
        level=Level.WELL,
        agent="high",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        bounds=(Bound("p1", EventKind.SET_LRAT, BoundSense.FLOOR, 40.0),),
    )
    merged = merge_proposals((primary, low, high), 0)
    assert merged.decisions[0].value == 40.0


def test_the_trace_names_who_restricted_whom() -> None:
    primary = Proposal(
        level=Level.WELL,
        agent="i1",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        bounds=(Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 200.0),),
    )
    tight = Proposal(
        level=Level.WELL,
        agent="InjectionCapAgent",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        bounds=(Bound("i1", EventKind.SET_RATE, BoundSense.CEILING, 90.0),),
    )
    merged = merge_proposals((primary, tight), 0)
    restrictions = [
        leveled
        for leveled in merged.trace
        if leveled.entry.decision.startswith("RESTRICTED_")
    ]
    assert len(restrictions) == 1
    entry = restrictions[0].entry
    assert entry.decision == "RESTRICTED_CEILING_SET_RATE_BY_InjectionCapAgent"
    assert entry.well == "i1"
    assert entry.inputs["standing_bound_m3_per_day"] == 200.0
    assert entry.inputs["applied_bound_m3_per_day"] == 90.0


def test_the_trace_records_a_veto_as_its_own_kind_of_entry() -> None:
    primary = Proposal(
        level=Level.WELL,
        agent="i1",
        decisions=(
            ControlEvent(
                control_step=0, well="i1", kind=EventKind.SET_RATE, value=10.0
            ),
        ),
        rule_by_decision=(Rule.R1,),
        trace=(),
    )
    vetoer = Proposal(
        level=Level.WELL,
        agent="VetoWellAgent",
        decisions=(),
        rule_by_decision=(),
        trace=(),
        verdict=Verdict.VETO,
        veto_reason="MAINTENANCE",
    )
    merged = merge_proposals((primary, vetoer), 0)
    vetoes = [
        leveled
        for leveled in merged.trace
        if leveled.entry.decision == "VETO_MAINTENANCE"
    ]
    assert len(vetoes) == 1
    assert merged.veto_reason == "MAINTENANCE"


def test_merging_proposals_of_two_levels_is_refused() -> None:
    field_side = Proposal(
        level=Level.FIELD, agent="field", decisions=(), rule_by_decision=(), trace=()
    )
    well_side = Proposal(
        level=Level.WELL, agent="i1", decisions=(), rule_by_decision=(), trace=()
    )
    with pytest.raises(ValueError, match="разных уровней"):
        merge_proposals((field_side, well_side), 0)


def test_merging_nothing_is_refused_instead_of_returning_an_empty_step() -> None:
    with pytest.raises(ValueError, match="пустого списка"):
        merge_proposals((), 0)


def test_a_capping_agent_lowers_setpoints_of_the_real_step(
    context: RuleContext,
) -> None:
    plain = a_step(context)
    capped = a_step(
        context,
        AgentRegistry(
            agents=(
                FieldCoordinator(),
                GroupAllocator(),
                WellExecutor(),
                InjectionCapAgent(cap_m3_per_day=10.0, wells=("i1", "i2")),
            )
        ),
    )
    injections_before = {
        event.well: event.value
        for event in plain.decisions
        if event.kind is EventKind.SET_RATE
    }
    injections_after = {
        event.well: event.value
        for event in capped.decisions
        if event.kind is EventKind.SET_RATE
    }
    assert injections_before
    assert set(injections_after) == set(injections_before)
    for well, value in injections_after.items():
        assert value is not None
        assert value <= 10.0
        assert injections_before[well] is not None
        assert value <= injections_before[well]


def test_a_capping_agent_never_raises_a_setpoint(context: RuleContext) -> None:
    plain = a_step(context)
    generous = a_step(
        context,
        AgentRegistry(
            agents=(
                FieldCoordinator(),
                GroupAllocator(),
                WellExecutor(),
                InjectionCapAgent(cap_m3_per_day=1e9, wells=("i1", "i2")),
            )
        ),
    )
    assert generous.decisions == plain.decisions


def test_a_vetoing_well_agent_removes_decisions_from_the_step(
    context: RuleContext,
) -> None:
    plain = a_step(context)
    vetoed = a_step(
        context,
        AgentRegistry(
            agents=(
                FieldCoordinator(),
                GroupAllocator(),
                WellExecutor(),
                VetoWellAgent(),
            )
        ),
    )
    assert plain.decisions
    assert vetoed.decisions == ()
    assert any(
        leveled.entry.decision == "VETO_MAINTENANCE"
        for leveled in vetoed.trace.entries
    )


def test_the_step_is_the_same_however_the_extra_agents_were_registered(
    context: RuleContext,
) -> None:
    cap = InjectionCapAgent(cap_m3_per_day=12.0, wells=("i1", "i2"))
    recorder_a = RecordingWellAgent(calls=[])
    recorder_b = RecordingWellAgent(calls=[])
    forward = a_step(
        context,
        AgentRegistry(
            agents=(
                FieldCoordinator(),
                GroupAllocator(),
                WellExecutor(),
                recorder_a,
                cap,
            )
        ),
    )
    backward = a_step(
        context,
        AgentRegistry(
            agents=(
                cap,
                recorder_b,
                WellExecutor(),
                GroupAllocator(),
                FieldCoordinator(),
            )
        ),
    )
    assert forward.decisions == backward.decisions
    assert full_trace(forward) == full_trace(backward)


def test_a_level_left_without_an_agent_reports_an_error(
    context: RuleContext,
) -> None:
    with pytest.raises(ValueError, match="не обслуживает ни один агент"):
        a_step(
            context,
            AgentRegistry(agents=(FieldCoordinator(), GroupAllocator())),
        )
