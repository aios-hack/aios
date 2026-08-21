from __future__ import annotations

import pytest

from aios_backend.core.contracts import (
    ActiveControlMode,
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
    StateAtDate,
)
from aios_backend.domain.economics import (
    DOWNSIZE_THRESHOLD_M3_PER_DAY,
    ESP_CATALOG_2007,
    EspEventKind,
    EspStateMachine,
)

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)
NO_EXCLUDED: frozenset[int] = frozenset()
N_INTERVALS_TEST = 4


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


def build_states(liquid_rates: list[float], well: str = "W1") -> list[StateAtDate]:
    return [
        make_state(deck_step, well=well, liquid=liquid)
        for deck_step, liquid in enumerate(liquid_rates)
    ]


def make_machine(
    charge: ChargeInitialEsp = ChargeInitialEsp.NOT_CHARGED,
) -> EspStateMachine:
    return EspStateMachine(NORMATIVES, charge)


def track(
    liquid_rates: list[float],
    charge: ChargeInitialEsp = ChargeInitialEsp.NOT_CHARGED,
    excluded: frozenset[int] = NO_EXCLUDED,
):
    return make_machine(charge).track_well(
        "W1", build_states(liquid_rates), N_INTERVALS_TEST, excluded
    )


def test_start_size_determined_by_history_prefix() -> None:
    control_tail = [90.0, 150.0, 150.0, 150.0]
    track_low = track([55.0, 55.0, 55.0, 55.0] + control_tail)
    track_high = track([90.0, 90.0, 90.0, 90.0] + control_tail)
    assert track_low.nominal_by_deck_step[3] == 50.0
    assert track_high.nominal_by_deck_step[3] == 80.0
    assert [e.new_nominal for e in track_low.events] == [80.0, 125.0]
    assert [e.new_nominal for e in track_high.events] == [125.0]
    assert track_low.total_capex_rub == 1_850_000.0 + 2_750_000.0
    assert track_high.total_capex_rub == 2_750_000.0


def test_gradual_upsize_costs_8_65m() -> None:
    result = track([90.0, 90.0, 90.0, 90.0, 110.0, 150.0, 150.0, 150.0])
    assert [e.kind for e in result.events] == [EspEventKind.UPSIZE, EspEventKind.UPSIZE]
    assert [(e.previous_nominal, e.new_nominal) for e in result.events] == [
        (80.0, 100.0),
        (100.0, 125.0),
    ]
    assert result.total_capex_rub == 2_300_000.0 + 2_750_000.0
    assert result.total_opex_rub == 2 * 1_800_000.0
    assert result.total_capex_rub + result.total_opex_rub == 8_650_000.0


def test_jump_upsize_costs_4_55m() -> None:
    result = track([90.0, 90.0, 90.0, 90.0, 150.0, 150.0, 150.0, 150.0])
    assert len(result.events) == 1
    event = result.events[0]
    assert event.kind is EspEventKind.UPSIZE
    assert event.previous_nominal == 80.0
    assert event.new_nominal == 125.0
    assert event.capex_rub == 2_750_000.0
    assert event.opex_rub == 1_800_000.0
    assert result.total_capex_rub + result.total_opex_rub == 4_550_000.0


def test_history_upsize_not_charged_control_upsize_charged() -> None:
    result = track([55.0, 90.0, 90.0, 90.0, 150.0, 150.0, 150.0, 150.0])
    assert result.nominal_by_deck_step[1] == 80.0
    assert len(result.events) == 1
    assert result.events[0].deck_step == 4
    assert result.events[0].new_nominal == 125.0


def test_downsize_only_beyond_threshold() -> None:
    no_downsize = track([260.0, 260.0, 260.0, 110.0, 110.0, 110.0, 110.0, 110.0])
    assert no_downsize.events == ()
    assert no_downsize.final_nominal == 250.0
    result = track([260.0, 260.0, 260.0, 110.0, 110.0, 109.0, 109.0, 109.0])
    assert len(result.events) == 1
    event = result.events[0]
    assert event.kind is EspEventKind.DOWNSIZE
    assert event.deck_step == 5
    assert event.previous_nominal == 250.0
    assert event.new_nominal == 125.0
    assert event.capex_rub == 2_750_000.0
    assert event.opex_rub == 1_800_000.0
    assert 250.0 - 210.0 <= DOWNSIZE_THRESHOLD_M3_PER_DAY


def test_initial_esp_not_charged_for_historical_well() -> None:
    result = track([90.0] * 8)
    assert result.events == ()
    assert result.final_nominal == 80.0
    assert result.total_capex_rub == 0.0


def test_initial_esp_not_charged_for_well_commissioned_inside_horizon() -> None:
    result = track([0.0, 0.0, 0.0, 0.0, 0.0, 90.0, 90.0, 90.0])
    assert result.events == ()
    assert result.nominal_by_deck_step[4] is None
    assert result.nominal_by_deck_step[5] == 80.0
    assert result.final_nominal == 80.0


def test_charged_option_mirrors_reference_branch() -> None:
    historical = track([90.0] * 8, charge=ChargeInitialEsp.CHARGED_AT_FIRST_STEP)
    assert len(historical.events) == 1
    assert historical.events[0].kind is EspEventKind.INITIAL
    assert historical.events[0].deck_step == 4
    assert historical.events[0].capex_rub == 1_850_000.0
    commissioned = track(
        [0.0, 0.0, 0.0, 0.0, 0.0, 90.0, 90.0, 90.0],
        charge=ChargeInitialEsp.CHARGED_AT_FIRST_STEP,
    )
    assert len(commissioned.events) == 1
    assert commissioned.events[0].kind is EspEventKind.INITIAL
    assert commissioned.events[0].deck_step == 5


def test_conversion_to_injection_gives_no_esp() -> None:
    states = build_states([90.0, 90.0, 90.0]) + [
        make_state(deck_step, liquid=0.0, injection=80.0)
        for deck_step in range(3, 8)
    ]
    result = make_machine().track_well("W1", states, N_INTERVALS_TEST, NO_EXCLUDED)
    assert result.events == ()
    assert result.final_nominal == 80.0
    assert result.total_capex_rub == 0.0
    assert result.total_opex_rub == 0.0


def test_excluded_row_fires_no_event() -> None:
    rates = [90.0, 90.0, 90.0, 90.0, 150.0, 90.0, 90.0, 90.0]
    with_spike = track(rates)
    assert len(with_spike.events) == 1
    excluded = track(rates, excluded=frozenset({4}))
    assert excluded.events == ()
    assert excluded.final_nominal == 80.0


def test_sparse_trajectory_rejected() -> None:
    states = build_states([90.0] * 8)
    states[4] = make_state(6, liquid=90.0)
    with pytest.raises(ValueError):
        make_machine().track_well("W1", states, N_INTERVALS_TEST, NO_EXCLUDED)


def test_foreign_well_rejected() -> None:
    states = build_states([90.0] * 8)
    states[2] = make_state(2, well="W2", liquid=90.0)
    with pytest.raises(ValueError):
        make_machine().track_well("W1", states, N_INTERVALS_TEST, NO_EXCLUDED)


def test_no_history_rejected() -> None:
    with pytest.raises(ValueError):
        make_machine().track_well(
            "W1", build_states([90.0] * 4), N_INTERVALS_TEST, NO_EXCLUDED
        )


def test_excluded_step_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        make_machine().track_well(
            "W1", build_states([90.0] * 8), N_INTERVALS_TEST, frozenset({8})
        )


def test_empty_catalog_rejected() -> None:
    normatives = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=())
    with pytest.raises(ValueError):
        EspStateMachine(normatives, ChargeInitialEsp.NOT_CHARGED)
