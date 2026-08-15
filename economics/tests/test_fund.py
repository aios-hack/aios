from __future__ import annotations

import pytest

from contracts import (
    ActiveControlMode,
    DEFAULT_NORMATIVES_2007,
    IntervalResponse,
    NormativeSet,
    StateAtDate,
)
from economics import (
    FundState,
    classify_fund_state,
    track_well,
    transition_costs,
)

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=())


def make_state(
    deck_step: int,
    well: str = "W1",
    liquid: float = 0.0,
    injection: float = 0.0,
) -> StateAtDate:
    return StateAtDate(
        deck_date_index=deck_step,
        well=well,
        liquid_rate=liquid,
        oil_rate=liquid * 0.5,
        injection_rate=injection,
        thp=10.0,
        bhp=100.0,
        well_efficiency=1.0,
        active_control_mode=ActiveControlMode.UNKNOWN,
    )


def make_response(
    control_step: int,
    well: str = "W1",
    oil: float = 1.0,
    liquid: float = 1.0,
    injection: float = 0.0,
) -> IntervalResponse:
    return IntervalResponse(
        control_step=control_step,
        well=well,
        oil_mass_delta=oil,
        liquid_volume_delta=liquid,
        injection_volume_delta=injection,
    )


def build_states(
    rates_by_deck_step: list[tuple[float, float]], well: str = "W1"
) -> list[StateAtDate]:
    return [
        make_state(deck_step, well=well, liquid=liquid, injection=injection)
        for deck_step, (liquid, injection) in enumerate(rates_by_deck_step)
    ]


def build_responses(n_intervals: int, well: str = "W1") -> list[IntervalResponse]:
    return [make_response(k, well=well) for k in range(n_intervals)]


def test_history_rolled_no_transition_at_first_control_step() -> None:
    states = build_states([(50.0, 0.0)] * 8)
    track = track_well("W1", states, build_responses(5), NORMATIVES)
    assert track.transitions == ()
    assert track.state_by_control_step[0] is FundState.PROD_ACTIVE
    assert all(track.active_by_control_step.values())
    assert sum(track.event_costs_by_control_step.values()) == 0.0


def test_setpoint_changes_are_free() -> None:
    rates = [(50.0, 0.0), (30.0, 0.0), (70.0, 0.0), (10.0, 0.0), (90.0, 0.0), (20.0, 0.0), (60.0, 0.0), (40.0, 0.0)]
    track = track_well("W1", build_states(rates), build_responses(5), NORMATIVES)
    assert track.transitions == ()
    assert sum(track.event_costs_by_control_step.values()) == 0.0


def test_stop_by_fact_charges_event_cost() -> None:
    rates = [(50.0, 0.0)] * 5 + [(0.0, 0.0)] * 3
    track = track_well("W1", build_states(rates), build_responses(5), NORMATIVES)
    assert len(track.transitions) == 1
    transition = track.transitions[0]
    assert transition.control_step == 2
    assert transition.previous is FundState.PROD_ACTIVE
    assert transition.current is FundState.SHUT
    assert transition.event_cost_rub == NORMATIVES.event_cost_rub
    assert transition.event_cost_rub == 1_000_000.0
    assert transition.conversion_opex_rub == 0.0
    assert track.active_by_control_step[2] is False


def test_stop_at_control_step_zero_boundary() -> None:
    rates = [(50.0, 0.0)] * 3 + [(0.0, 0.0)] * 5
    track = track_well("W1", build_states(rates), build_responses(5), NORMATIVES)
    assert len(track.transitions) == 1
    assert track.transitions[0].control_step == 0
    assert track.transitions[0].event_cost_rub == NORMATIVES.event_cost_rub


def test_transition_at_last_interval_boundary() -> None:
    rates = [(50.0, 0.0)] * 7 + [(0.0, 0.0)]
    responses = build_responses(5)
    track = track_well("W1", build_states(rates), responses, NORMATIVES)
    last_control_step = len(responses) - 1
    assert len(track.transitions) == 1
    assert track.transitions[0].control_step == last_control_step
    assert track.state_by_control_step[last_control_step] is FundState.SHUT


def test_restart_charges_event_cost() -> None:
    rates = [(50.0, 0.0)] * 4 + [(0.0, 0.0), (0.0, 0.0), (50.0, 0.0), (50.0, 0.0)]
    track = track_well("W1", build_states(rates), build_responses(5), NORMATIVES)
    kinds = [(t.previous, t.current, t.event_cost_rub) for t in track.transitions]
    assert kinds == [
        (FundState.PROD_ACTIVE, FundState.SHUT, NORMATIVES.event_cost_rub),
        (FundState.SHUT, FundState.PROD_ACTIVE, NORMATIVES.event_cost_rub),
    ]
    assert sum(track.event_costs_by_control_step.values()) == 2 * NORMATIVES.event_cost_rub


def test_direct_conversion_costs_exactly_base_no_stop_no_esp() -> None:
    rates = [(50.0, 0.0)] * 5 + [(0.0, 80.0)] * 3
    track = track_well("W1", build_states(rates), build_responses(5), NORMATIVES)
    assert len(track.transitions) == 1
    transition = track.transitions[0]
    assert transition.previous is FundState.PROD_ACTIVE
    assert transition.current is FundState.INJ_ACTIVE
    assert transition.event_cost_rub == 0.0
    assert transition.conversion_opex_rub == NORMATIVES.conversion_base_cost_rub
    assert transition.conversion_opex_rub == 5_000_000.0
    assert sum(track.event_costs_by_control_step.values()) == 5_000_000.0
    assert track.active_by_control_step[2] is True


def test_commissioning_inside_horizon_is_not_a_start() -> None:
    rates = [(0.0, 0.0)] * 5 + [(50.0, 0.0)] * 3
    track = track_well("W1", build_states(rates), build_responses(5), NORMATIVES)
    assert track.state_by_control_step[0] is FundState.NOT_COMMISSIONED
    assert track.state_by_control_step[1] is FundState.NOT_COMMISSIONED
    assert len(track.transitions) == 1
    transition = track.transitions[0]
    assert transition.control_step == 2
    assert transition.previous is FundState.NOT_COMMISSIONED
    assert transition.current is FundState.PROD_ACTIVE
    assert transition.event_cost_rub == 0.0
    assert transition.conversion_opex_rub == 0.0
    assert track.active_by_control_step[1] is False
    assert track.active_by_control_step[2] is True


def test_negative_row_excluded_entirely_not_zeroed() -> None:
    rates = [(50.0, 0.0)] * 5 + [(0.0, 0.0)] + [(50.0, 0.0)] * 2
    responses = build_responses(5)
    responses[2] = make_response(2, liquid=-1.0)
    track = track_well("W1", build_states(rates), responses, NORMATIVES)
    assert 2 not in track.state_by_control_step
    assert 2 not in track.active_by_control_step
    assert 2 not in track.event_costs_by_control_step
    assert track.transitions == ()
    assert sum(track.event_costs_by_control_step.values()) == 0.0
    assert track.state_by_control_step[3] is FundState.PROD_ACTIVE


def test_negative_row_at_last_interval_dropped() -> None:
    rates = [(50.0, 0.0)] * 8
    responses = build_responses(5)
    responses[4] = make_response(4, oil=-1.0)
    track = track_well("W1", build_states(rates), responses, NORMATIVES)
    assert sorted(track.state_by_control_step) == [0, 1, 2, 3]
    assert track.transitions == ()


def test_classify_requires_single_role() -> None:
    with pytest.raises(ValueError):
        classify_fund_state(make_state(0, liquid=10.0, injection=10.0), True)


def test_injection_to_production_rejected() -> None:
    with pytest.raises(ValueError):
        transition_costs(FundState.INJ_ACTIVE, FundState.PROD_ACTIVE, NORMATIVES)


def test_foreign_well_rejected() -> None:
    states = build_states([(50.0, 0.0)] * 8)
    states[3] = make_state(3, well="W2", liquid=50.0)
    with pytest.raises(ValueError):
        track_well("W1", states, build_responses(5), NORMATIVES)


def test_sparse_deck_steps_rejected() -> None:
    states = build_states([(50.0, 0.0)] * 8)
    states[4] = make_state(6, liquid=50.0)
    with pytest.raises(ValueError):
        track_well("W1", states, build_responses(5), NORMATIVES)


def test_no_history_rejected() -> None:
    states = build_states([(50.0, 0.0)] * 5)
    with pytest.raises(ValueError):
        track_well("W1", states, build_responses(5), NORMATIVES)
