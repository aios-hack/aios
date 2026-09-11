from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    IntervalResponse,
    N_INTERVALS,
    OperatingStatus,
    ResponseArtifact,
    Role,
    Rule,
    Schedule,
    ScheduleMeta,
    WellState,
)

from backend.domain.policy import (
    PolicyState,
    RuleContext,
    RuleFlags,
    default_theta,
    run_step,
)
from backend.contexts.policy.domain.agents import (
    APPROACH_FRACTION,
    DEFAULT_REGISTRY,
    PRESSURE_AGENT,
    PRESSURE_AGENT_RANK,
    PRESSURE_CEILING_DECISION,
    PRESSURE_REGISTRY,
    AgentRegistry,
    FieldCoordinator,
    GroupAllocator,
    PressureAgent,
    PressureCorridor,
    WaterAgent,
    WellExecutor,
    pressure_corridor_of,
    with_agents,
)
from backend.contexts.policy.domain.agents.registry import rank_of
from backend.contexts.policy.domain.budget import (
    baseline_injection_by_step,
    interval_produced_water_rate_m3_per_day,
)
from backend.contexts.policy.domain.levels import Level
from backend.contexts.policy.domain.trace import trace_hash
from tests.backend.contexts.policy.conftest import (
    OIL_DENSITY_T_PER_M3,
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

PRESSURE_FLOOR_BAR = 200.0
PRESSURE_CEILING_BAR = 300.0
MID_CORRIDOR_BAR = 250.0
NEAR_CEILING_BAR = 295.0
NEAR_FLOOR_BAR = 205.0


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


def with_limits(context: RuleContext, pressure_bar: float | None) -> RuleContext:
    return replace(
        context,
        field_pressure_bar=pressure_bar,
        pressure_floor_bar=PRESSURE_FLOOR_BAR,
        pressure_ceiling_bar=PRESSURE_CEILING_BAR,
    )


def without_pressure(*extra) -> AgentRegistry:
    return AgentRegistry(
        agents=(FieldCoordinator(), WaterAgent(), GroupAllocator(), WellExecutor())
        + extra
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


def only_r1_flags() -> RuleFlags:
    return RuleFlags(enabled={rule: rule is Rule.R1 for rule in Rule})


def every_rule_flags() -> RuleFlags:
    return RuleFlags(enabled={rule: True for rule in Rule})


def a_step(
    context: RuleContext,
    registry: AgentRegistry | None = None,
    flags: RuleFlags | None = None,
):
    kwargs = {} if registry is None else {"registry": registry}
    return run_step(
        two_group_state(),
        context,
        default_theta(),
        only_r1_flags() if flags is None else flags,
        field_limit_m3_per_day=FIELD_LIMIT_M3_PER_DAY,
        **kwargs,
    )


def pressure_entries(result) -> list:
    return [
        leveled for leveled in result.trace.entries if leveled.agent == PRESSURE_AGENT
    ]


def setpoints(result, kind: EventKind) -> dict[str, float]:
    return {
        event.well: event.value
        for event in result.decisions
        if event.kind is kind and event.value is not None
    }


def test_pressure_agent_is_registered_and_ranked_after_the_water_agent() -> None:
    names = tuple(agent.name for agent in PRESSURE_REGISTRY.by_level(Level.FIELD))
    assert names == ("FieldCoordinator", "WaterAgent", PRESSURE_AGENT)
    agent = PRESSURE_REGISTRY.of(PRESSURE_AGENT)
    assert rank_of(agent) == PRESSURE_AGENT_RANK
    assert rank_of(agent) > rank_of(PRESSURE_REGISTRY.of("WaterAgent"))
    assert agent.level is Level.FIELD
    assert agent.responsibilities


def test_pressure_agent_joins_the_registry_by_one_line() -> None:
    extended = with_agents(DEFAULT_REGISTRY, WaterAgent(), PressureAgent())
    assert extended.names() == PRESSURE_REGISTRY.names()


def test_two_pressure_agents_on_one_rank_are_refused() -> None:
    with pytest.raises(ValueError, match="заявили ранг"):
        with_agents(PRESSURE_REGISTRY, PressureAgent(name="PressureAgentTwin"))


def test_without_pressure_in_the_context_the_step_is_bit_for_bit_the_same(
    context: RuleContext,
) -> None:
    scoped = two_group_context(context)
    assert scoped.field_pressure_bar is None
    assert scoped.pressure_floor_bar is None
    assert scoped.pressure_ceiling_bar is None
    before = a_step(scoped, without_pressure())
    after = a_step(scoped, PRESSURE_REGISTRY)
    assert after.decisions == before.decisions
    assert after.group_decisions == before.group_decisions
    assert after.allocation == before.allocation
    assert full_trace(after) == full_trace(before)
    assert trace_hash(after.trace.as_run_trace()) == trace_hash(
        before.trace.as_run_trace()
    )


def test_limits_without_a_pressure_reading_keep_the_step_bit_for_bit_the_same(
    context: RuleContext,
) -> None:
    scoped = with_limits(two_group_context(context), None)
    before = a_step(two_group_context(context), without_pressure())
    after = a_step(scoped, PRESSURE_REGISTRY)
    assert after.decisions == before.decisions
    assert full_trace(after) == full_trace(before)
    assert not pressure_entries(after)


def test_a_pressure_reading_without_limits_keeps_the_agent_silent(
    context: RuleContext,
) -> None:
    scoped = replace(two_group_context(context), field_pressure_bar=MID_CORRIDOR_BAR)
    before = a_step(two_group_context(context), without_pressure())
    after = a_step(scoped, PRESSURE_REGISTRY)
    assert after.decisions == before.decisions
    assert full_trace(after) == full_trace(before)
    assert pressure_corridor_of(scoped) is None


def test_pressure_in_the_middle_of_the_corridor_keeps_the_agent_silent(
    context: RuleContext,
) -> None:
    scoped = with_limits(two_group_context(context), MID_CORRIDOR_BAR)
    before = a_step(two_group_context(context), without_pressure())
    after = a_step(scoped, PRESSURE_REGISTRY)
    assert not pressure_entries(after)
    assert after.decisions == before.decisions
    assert full_trace(after) == full_trace(before)


def test_pressure_near_the_ceiling_caps_injection_and_records_the_reason(
    context: RuleContext,
) -> None:
    scoped = with_limits(two_group_context(context), NEAR_CEILING_BAR)
    plain = a_step(two_group_context(context), without_pressure())
    capped = a_step(scoped, PRESSURE_REGISTRY)

    entries = pressure_entries(capped)
    assert {leveled.entry.well for leveled in entries} == {"i1", "i2"}
    for leveled in entries:
        assert leveled.level is Level.FIELD
        assert leveled.entry.decision == PRESSURE_CEILING_DECISION
        assert leveled.entry.inputs["field_pressure_bar"] == NEAR_CEILING_BAR
        assert leveled.entry.inputs["pressure_limit_bar"] == PRESSURE_CEILING_BAR
        assert leveled.entry.inputs["limit_side"] == 1.0
        assert leveled.entry.inputs["approach_margin_bar"] == pytest.approx(
            (PRESSURE_CEILING_BAR - PRESSURE_FLOOR_BAR) * APPROACH_FRACTION
        )

    before = setpoints(plain, EventKind.SET_RATE)
    after = setpoints(capped, EventKind.SET_RATE)
    assert set(after) == set(before)
    assert before
    assert all(after[well] <= before[well] for well in before)
    assert any(after[well] < before[well] for well in before)


def test_pressure_near_the_floor_caps_liquid_offtake(context: RuleContext) -> None:
    scoped = with_limits(two_group_context(context), NEAR_FLOOR_BAR)
    flags = every_rule_flags()
    plain = a_step(two_group_context(context), without_pressure(), flags)
    capped = a_step(scoped, PRESSURE_REGISTRY, flags)

    entries = pressure_entries(capped)
    assert {leveled.entry.well for leveled in entries} == {"p1", "p2"}
    for leveled in entries:
        assert leveled.entry.inputs["pressure_limit_bar"] == PRESSURE_FLOOR_BAR
        assert leveled.entry.inputs["limit_side"] == -1.0

    before = setpoints(plain, EventKind.SET_LRAT)
    after = setpoints(capped, EventKind.SET_LRAT)
    assert set(after) == set(before)
    assert before
    assert all(after[well] <= before[well] for well in before)
    assert any(after[well] < before[well] for well in before)


def test_the_closer_to_the_limit_the_harder_the_cut() -> None:
    far = PressureCorridor(
        value_bar=PRESSURE_CEILING_BAR - 10.0,
        floor_bar=PRESSURE_FLOOR_BAR,
        ceiling_bar=PRESSURE_CEILING_BAR,
        approach_fraction=APPROACH_FRACTION,
    )
    close = replace(far, value_bar=PRESSURE_CEILING_BAR - 1.0)
    assert far.near_ceiling()
    assert close.near_ceiling()
    assert close.relief_factor(
        close.ceiling_headroom_bar()
    ) < far.relief_factor(far.ceiling_headroom_bar())


def test_a_one_sided_corridor_measures_the_margin_from_the_declared_limit() -> None:
    corridor = PressureCorridor(
        value_bar=NEAR_CEILING_BAR,
        floor_bar=None,
        ceiling_bar=PRESSURE_CEILING_BAR,
        approach_fraction=APPROACH_FRACTION,
    )
    assert corridor.width_bar() == PRESSURE_CEILING_BAR
    assert corridor.near_ceiling()
    assert not corridor.near_floor()


def test_a_corridor_without_a_single_limit_is_refused() -> None:
    with pytest.raises(ValueError, match="без единого предела"):
        PressureCorridor(
            value_bar=MID_CORRIDOR_BAR,
            floor_bar=None,
            ceiling_bar=None,
            approach_fraction=APPROACH_FRACTION,
        )


def test_a_nonpositive_pressure_reading_is_refused() -> None:
    with pytest.raises(ValueError, match="неположительно"):
        PressureCorridor(
            value_bar=0.0,
            floor_bar=PRESSURE_FLOOR_BAR,
            ceiling_bar=PRESSURE_CEILING_BAR,
            approach_fraction=APPROACH_FRACTION,
        )


def test_an_empty_pressure_corridor_in_the_context_is_refused(
    context: RuleContext,
) -> None:
    with pytest.raises(ValueError, match="коридор пуст"):
        replace(
            context,
            pressure_floor_bar=PRESSURE_CEILING_BAR,
            pressure_ceiling_bar=PRESSURE_FLOOR_BAR,
        )


def test_a_nonpositive_pressure_in_the_context_is_refused(
    context: RuleContext,
) -> None:
    with pytest.raises(ValueError, match="неположительно"):
        replace(context, field_pressure_bar=0.0)


CONTROL_DATES = (
    date(2007, 1, 1),
    date(2007, 2, 1),
    date(2007, 3, 1),
)


def a_response(*items: IntervalResponse) -> ResponseArtifact:
    return ResponseArtifact(
        source_run_id="run",
        response_hash="0" * 64,
        state_at_date=(),
        interval_response=items,
    )


def an_interval(
    control_step: int, well: str, oil_t: float, liquid_m3: float
) -> IntervalResponse:
    return IntervalResponse(
        control_step=control_step,
        well=well,
        oil_mass_delta=oil_t,
        liquid_volume_delta=liquid_m3,
        injection_volume_delta=0.0,
    )


def original_interval_produced_water(
    response: ResponseArtifact,
    control_step: int,
    control_dates,
    oil_density_t_per_m3: float,
) -> float:
    if oil_density_t_per_m3 <= 0.0:
        raise ValueError("плотность нефти должна быть положительной")
    days = (control_dates[control_step + 1] - control_dates[control_step]).days
    if days <= 0:
        raise ValueError(f"control_step={control_step}: неположительная длина интервала")
    water_volume = 0.0
    for item in response.interval_response:
        if item.control_step != control_step:
            continue
        oil_volume = max(0.0, item.oil_mass_delta) / oil_density_t_per_m3
        water_volume += max(0.0, item.liquid_volume_delta - oil_volume)
    return water_volume / days


def original_baseline_injection_by_step(schedule: Schedule):
    current = {
        well: (
            float(state.setpoint or 0.0)
            if state.operating_status is OperatingStatus.OPEN
            else 0.0
        )
        for well, state in schedule.initial_state.items()
    }
    by_step: dict[int, list[ControlEvent]] = {}
    for event in schedule.control_events:
        by_step.setdefault(event.control_step, []).append(event)
    dense = []
    for step in range(schedule.meta.n_intervals):
        for event in by_step.get(step, ()):
            if event.kind is EventKind.SET_RATE:
                current[event.well] = float(event.value or 0.0)
            elif event.kind is EventKind.SHUT:
                current[event.well] = 0.0
        dense.append(dict(current))
    return tuple(dense)


PRODUCED_WATER_CASES = (
    a_response(an_interval(0, "p1", 30.0, 100.0)),
    a_response(
        an_interval(0, "p1", 30.0, 100.0),
        an_interval(0, "p2", 0.0, 60.0),
        an_interval(1, "p1", 10.0, 90.0),
    ),
    a_response(an_interval(0, "p1", 200.0, 10.0)),
    a_response(an_interval(0, "p1", -5.0, 40.0)),
    a_response(),
)


@pytest.mark.parametrize("response", PRODUCED_WATER_CASES)
@pytest.mark.parametrize("step", (0, 1))
def test_ported_produced_water_matches_the_original(
    response: ResponseArtifact, step: int
) -> None:
    assert interval_produced_water_rate_m3_per_day(
        response, step, CONTROL_DATES, OIL_DENSITY_T_PER_M3
    ) == original_interval_produced_water(
        response, step, CONTROL_DATES, OIL_DENSITY_T_PER_M3
    )


def test_ported_produced_water_refuses_a_nonpositive_density() -> None:
    with pytest.raises(ValueError, match="плотность нефти"):
        interval_produced_water_rate_m3_per_day(
            PRODUCED_WATER_CASES[0], 0, CONTROL_DATES, 0.0
        )


def test_ported_produced_water_refuses_a_step_off_the_axis() -> None:
    with pytest.raises(ValueError, match=r"вне 0"):
        interval_produced_water_rate_m3_per_day(
            PRODUCED_WATER_CASES[0], N_INTERVALS, CONTROL_DATES, OIL_DENSITY_T_PER_M3
        )


def test_ported_produced_water_refuses_a_short_date_axis() -> None:
    with pytest.raises(ValueError, match="правая граница интервала"):
        interval_produced_water_rate_m3_per_day(
            PRODUCED_WATER_CASES[0], 2, CONTROL_DATES, OIL_DENSITY_T_PER_M3
        )


def a_schedule(
    initial: dict[str, WellState], events: tuple[ControlEvent, ...], n_intervals: int
) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=tuple(sorted(initial)), n_intervals=n_intervals),
        initial_state=initial,
        fixed_deck_events=(),
        control_events=events,
    )


def an_open(setpoint: float) -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.INJ,
        operating_status=OperatingStatus.OPEN,
        setpoint=setpoint,
    )


def a_shut() -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=Role.INJ,
        operating_status=OperatingStatus.SHUT,
        setpoint=0.0,
    )


BASELINE_CASES = (
    a_schedule({"i1": an_open(100.0)}, (), 3),
    a_schedule({"i1": a_shut()}, (), 3),
    a_schedule(
        {"i1": an_open(100.0), "i2": a_shut()},
        (
            ControlEvent(
                control_step=1, well="i1", kind=EventKind.SET_RATE, value=250.0
            ),
            ControlEvent(control_step=2, well="i1", kind=EventKind.SHUT),
            ControlEvent(
                control_step=0, well="i2", kind=EventKind.SET_RATE, value=70.0
            ),
        ),
        4,
    ),
)


@pytest.mark.parametrize("schedule", BASELINE_CASES)
def test_ported_baseline_injection_matches_the_original(schedule: Schedule) -> None:
    assert baseline_injection_by_step(schedule) == original_baseline_injection_by_step(
        schedule
    )


def test_ported_baseline_injection_spans_the_whole_horizon() -> None:
    schedule = BASELINE_CASES[2]
    dense = baseline_injection_by_step(schedule)
    assert len(dense) == schedule.meta.n_intervals
    assert dense[0]["i2"] == 70.0
    assert dense[1]["i1"] == 250.0
    assert dense[2]["i1"] == 0.0
