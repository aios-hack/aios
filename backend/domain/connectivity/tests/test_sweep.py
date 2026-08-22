from __future__ import annotations

import pytest

from backend.domain.connectivity import (
    Amplitude,
    Level,
    ProbeSelection,
    WindowSteps,
    cumulative_liquid,
    injection_setpoints,
    mean_injection_rate,
    perturbed_schedule,
    responders_of,
    sweep_targets,
)
from backend.core.contracts import (
    ActiveControlMode,
    ControlEvent,
    EventKind,
    IntervalResponse,
    Schedule,
    ScheduleMeta,
    StateAtDate,
)

INJECTORS = ("I1", "I2")
PRODUCERS = ("P1", "P2")
STEPS = WindowSteps(first=0, last=11)
T0_INDEX = 146


def a_schedule() -> Schedule:
    events: list[ControlEvent] = []
    for step in range(24):
        for well in INJECTORS:
            events.append(
                ControlEvent(
                    control_step=step, well=well, kind=EventKind.SET_RATE, value=30.0
                )
            )
            events.append(
                ControlEvent(control_step=step, well=well, kind=EventKind.OPEN)
            )
        for well in PRODUCERS:
            events.append(
                ControlEvent(
                    control_step=step, well=well, kind=EventKind.SET_LRAT, value=50.0
                )
            )
            events.append(
                ControlEvent(control_step=step, well=well, kind=EventKind.OPEN)
            )
    return Schedule(
        meta=ScheduleMeta(wells=tuple(sorted(INJECTORS + PRODUCERS))),
        initial_state={},
        fixed_deck_events=(),
        control_events=tuple(events),
    )


def a_state(well: str, deck_date_index: int, injection: float) -> StateAtDate:
    return StateAtDate(
        deck_date_index=deck_date_index,
        well=well,
        liquid_rate=0.0,
        oil_rate=0.0,
        injection_rate=injection,
        thp=10.0,
        bhp=250.0,
        well_efficiency=1.0,
        active_control_mode=ActiveControlMode.RATE_TARGET,
    )


def test_perturbation_only_touches_the_named_wells_inside_the_window() -> None:
    baseline = a_schedule()
    perturbed = perturbed_schedule(
        baseline, {"I1": 36.0}, STEPS, provenance="sweep +20% I1"
    )
    assert len(perturbed.control_events) == len(baseline.control_events)
    changed = [
        e
        for e in perturbed.control_events
        if e.kind is EventKind.SET_RATE and e.value == 36.0
    ]
    assert {e.well for e in changed} == {"I1"}
    assert {e.control_step for e in changed} == set(range(STEPS.first, STEPS.last + 1))
    untouched = [
        e
        for e in perturbed.control_events
        if e.kind is EventKind.SET_RATE and e.well == "I2"
    ]
    assert all(e.value == 30.0 for e in untouched)


def test_perturbation_outside_the_window_is_left_alone() -> None:
    baseline = a_schedule()
    perturbed = perturbed_schedule(baseline, {"I1": 36.0}, STEPS, provenance="p")
    after = [
        e
        for e in perturbed.control_events
        if e.kind is EventKind.SET_RATE
        and e.well == "I1"
        and e.control_step > STEPS.last
    ]
    assert after and all(e.value == 30.0 for e in after)


def test_perturbation_that_would_not_materialise_is_refused() -> None:
    """Моков нет: если в окне нет уставки закачки, это ошибка, а не тихое ничего."""

    baseline = a_schedule()
    with pytest.raises(ValueError, match="не материализовалось"):
        perturbed_schedule(baseline, {"I9": 36.0}, STEPS, provenance="p")


def test_setpoint_is_resolved_when_control_starts_after_the_window_edge() -> None:
    """Реальный Model_Z: у части нагнетательных первая SET_RATE стоит на шаге 1,

    а не 0 — уставка на t0 живёт в неизменяемой части дека. Замер обязан взять
    ближайшую известную уставку, а не объявить скважину неуправляемой
    (проверено 16.08 на скважинах 110 и 17).
    """

    baseline = a_schedule()
    late = Schedule(
        meta=baseline.meta,
        initial_state={},
        fixed_deck_events=(),
        control_events=tuple(
            e
            for e in baseline.control_events
            if not (
                e.well == "I1"
                and e.kind is EventKind.SET_RATE
                and e.control_step == 0
            )
        ),
    )
    resolved = injection_setpoints(late, INJECTORS, 0)
    assert resolved == {"I1": 30.0, "I2": 30.0}


def test_a_well_absent_from_the_schedule_entirely_is_refused() -> None:
    with pytest.raises(ValueError, match="ни одной уставки"):
        injection_setpoints(a_schedule(), ("I9",), 0)


def test_targets_are_taken_from_the_baseline_setpoints_not_a_constant() -> None:
    baseline = a_schedule()
    current = injection_setpoints(baseline, INJECTORS, STEPS.first)
    assert current == {"I1": 30.0, "I2": 30.0}
    selection = ProbeSelection(
        wells=("I1", "I2", "I3"), neighbour_count={"I1": 3, "I2": 5, "I3": 8}
    )
    amplitude = Amplitude(
        base_level_m3_per_day=30.0,
        step_low_m3_per_day=6.0,
        step_high_m3_per_day=6.0,
    )
    with pytest.raises(ValueError, match="I3"):
        sweep_targets(selection, amplitude, current, Level.HIGH)


def test_high_and_low_targets_are_symmetric_around_the_baseline() -> None:
    amplitude = Amplitude(
        base_level_m3_per_day=30.0,
        step_low_m3_per_day=6.0,
        step_high_m3_per_day=6.0,
    )
    selection = ProbeSelection(
        wells=("I1", "I2", "I3"), neighbour_count={"I1": 3, "I2": 5, "I3": 8}
    )
    current = {"I1": 30.0, "I2": 20.0, "I3": 40.0}
    raised = sweep_targets(selection, amplitude, current, Level.HIGH)
    lowered = sweep_targets(selection, amplitude, current, Level.LOW)
    for well, level in current.items():
        assert raised[well] == level + 6.0
        assert lowered[well] == level - 6.0


def test_actual_injectivity_is_read_from_the_response_not_the_plan() -> None:
    states = [
        a_state("I1", T0_INDEX + 1 + step, 28.0) for step in range(STEPS.length)
    ]
    states += [a_state("I1", T0_INDEX + 1 + 50, 99.0)]
    measured = mean_injection_rate(states, "I1", T0_INDEX, STEPS)
    assert measured == pytest.approx(28.0)


def test_missing_response_in_the_window_is_an_error() -> None:
    with pytest.raises(ValueError, match="нет ни одной записи"):
        mean_injection_rate([], "I1", T0_INDEX, STEPS)


def test_response_is_cumulative_production_in_the_window() -> None:
    """§8.2: отклик — накопленная добыча в окне, не мгновенный дебит."""

    intervals = [
        IntervalResponse(
            control_step=step,
            well=well,
            oil_mass_delta=1.0,
            liquid_volume_delta=100.0,
            injection_volume_delta=0.0,
        )
        for step in range(24)
        for well in PRODUCERS
    ]
    inside = cumulative_liquid(intervals, PRODUCERS, STEPS)
    assert inside == pytest.approx(100.0 * STEPS.length * len(PRODUCERS))
    single = cumulative_liquid(intervals, ("P1",), STEPS)
    assert single == pytest.approx(100.0 * STEPS.length)


def test_responders_must_be_declared() -> None:
    assert responders_of("I1", {"I1": ["P2", "P1", "P1"]}) == ("P1", "P2")
    with pytest.raises(ValueError):
        responders_of("I9", {"I1": ["P1"]})
    with pytest.raises(ValueError):
        responders_of("I1", {"I1": []})


def test_empty_window_is_refused() -> None:
    with pytest.raises(ValueError):
        WindowSteps(first=10, last=9)
