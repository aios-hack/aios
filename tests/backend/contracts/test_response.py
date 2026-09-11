import pytest

from backend.contexts.reservoir.domain.response import (
    ActiveControlMode,
    IntervalResponse,
    StateAtDate,
    is_excluded_by_negative_rule,
    join_by_control_step,
)
from backend.contexts.reservoir.domain.response import N_DECK_DATES, N_INTERVALS


def _resp(oil: float = 100.0, liquid: float = 200.0, injection: float = 300.0) -> IntervalResponse:
    return IntervalResponse(
        control_step=0,
        well="42",
        oil_mass_delta=oil,
        liquid_volume_delta=liquid,
        injection_volume_delta=injection,
    )


def _state(index: int) -> StateAtDate:
    return StateAtDate(
        deck_date_index=index,
        well="42",
        liquid_rate=20.0,
        oil_rate=5.0,
        injection_rate=0.0,
        thp=25.0,
        bhp=80.0,
        well_efficiency=1.0,
        active_control_mode=ActiveControlMode.RATE_TARGET,
    )


def test_axes_are_371_and_224() -> None:
    assert N_DECK_DATES == 371
    assert N_INTERVALS == 224


def test_interval_response_rejects_terminal_step() -> None:
    with pytest.raises(ValueError):
        IntervalResponse(
            control_step=224,
            well="42",
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=0.0,
        )


def test_negative_rule_excludes_row_on_any_negative_delta() -> None:
    assert not is_excluded_by_negative_rule(_resp())
    assert is_excluded_by_negative_rule(_resp(oil=-1.0))
    assert is_excluded_by_negative_rule(_resp(liquid=-1.0))
    assert is_excluded_by_negative_rule(_resp(injection=-1.0))


def test_negative_rule_keeps_zero_deltas() -> None:
    assert not is_excluded_by_negative_rule(_resp(oil=0.0, liquid=0.0, injection=0.0))


def test_join_aligns_first_and_last_interval() -> None:
    responses = {(k, "42"): _resp() for k in range(N_INTERVALS)}
    states = {(i, "42"): _state(i) for i in range(N_DECK_DATES)}
    pairs = join_by_control_step(responses, states, "42")

    assert len(pairs) == N_INTERVALS
    assert pairs[0].previous_state.deck_date_index == 146
    assert pairs[0].current_state.deck_date_index == 147
    assert pairs[-1].previous_state.deck_date_index == 369
    assert pairs[-1].current_state.deck_date_index == 370
