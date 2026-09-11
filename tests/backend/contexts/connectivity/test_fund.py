from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from backend.core.contracts import N_CONTROL_DATES, T0, Availability, OperatingStatus, Role

from backend.domain.connectivity import (
    DeckSchedule,
    FundHistory,
    Window,
    active_fund_at,
    active_fund_in_window,
    slice_windows,
)

END_OF_DECK = date(2025, 9, 1)
FULL_FUND_REACHED = date(2022, 1, 1)


def test_deck_axis_matches_control_scale(deck: DeckSchedule) -> None:
    assert deck.dates[0] == date(1994, 11, 1)
    assert deck.dates[-1] == END_OF_DECK
    assert len(deck.dates) - deck.dates.index(T0) == N_CONTROL_DATES


def test_injector_fund_at_t0_is_27(deck: DeckSchedule, history: FundHistory) -> None:
    fund = active_fund_at(deck, T0, history)
    assert len(fund.injectors) == 27
    assert fund.plan_width == 27


def test_injector_fund_reaches_41_by_2022(
    deck: DeckSchedule, history: FundHistory
) -> None:
    assert len(active_fund_at(deck, FULL_FUND_REACHED, history).injectors) == 41
    assert len(active_fund_at(deck, END_OF_DECK, history).injectors) == 41


def test_41_injectors_do_not_exist_in_early_window(
    deck: DeckSchedule, history: FundHistory
) -> None:
    early = active_fund_at(deck, T0, history)
    late = active_fund_at(deck, END_OF_DECK, history)
    assert set(early.injectors) < set(late.injectors)
    assert len(late.injectors) - len(early.injectors) == 14


def test_injector_fund_grows_monotonically(
    deck: DeckSchedule, history: FundHistory
) -> None:
    t0_index = deck.dates.index(T0)
    counts = [
        len(active_fund_at(deck, deck.dates[i], history).injectors)
        for i in range(t0_index, len(deck.dates))
    ]
    assert counts == sorted(counts)
    assert counts[0] == 27
    assert counts[-1] == 41


def test_producer_fund_at_t0(deck: DeckSchedule, history: FundHistory) -> None:
    fund = active_fund_at(deck, T0, history)
    assert len(fund.producers) == 57
    assert not set(fund.producers) & set(fund.injectors)


def test_not_commissioned_wells_are_outside_the_fund(
    deck: DeckSchedule, history: FundHistory
) -> None:
    fund = active_fund_at(deck, T0, history)
    assert len(fund.commissioned) == 84
    assert len(deck.wells) - len(fund.commissioned) == 19
    state = history.state_at(deck.date_index(T0))
    outside = [w for w, s in state.items() if s.availability is Availability.NOT_COMMISSIONED]
    assert set(outside).isdisjoint(fund.injectors)
    assert set(outside).isdisjoint(fund.producers)


def test_conversion_moves_well_from_producers_to_injectors(
    deck: DeckSchedule, history: FundHistory
) -> None:
    t0_index = deck.dates.index(T0)
    converted: list[str] = []
    for i in range(t0_index, len(deck.dates) - 1):
        before = history.state_at(i)
        after = history.state_at(i + 1)
        for well, state in after.items():
            if state.role is Role.INJ and before[well].role is Role.PROD:
                converted.append(well)
    assert converted
    for well in converted:
        assert well in active_fund_at(deck, END_OF_DECK, history).injectors


def test_every_shut_in_deck_is_the_producing_side_of_a_conversion(
    deck: DeckSchedule, history: FundHistory
) -> None:
    shut = [r for r in deck.records if r.operating_status is OperatingStatus.SHUT]
    assert shut
    for record in shut:
        same_date = [
            r
            for r in deck.records_at(record.deck_date_index)
            if r.well == record.well and r.role is Role.INJ
        ]
        assert same_date, f"{record.well}: SHUT без перевода под закачку"
    persisted = sum(
        1
        for state in history.states
        for well_state in state.values()
        if well_state.role is not Role.NONE
        and well_state.operating_status is OperatingStatus.SHUT
    )
    assert persisted == 0


def test_shut_well_would_leave_the_active_fund(
    deck: DeckSchedule, history: FundHistory
) -> None:
    fund = active_fund_at(deck, T0, history)
    victim = fund.injectors[0]
    state = dict(history.state_at(deck.date_index(T0)))
    state[victim] = replace(state[victim], operating_status=OperatingStatus.SHUT)
    patched = FundHistory(
        dates=history.dates,
        states=tuple(
            state if i == deck.date_index(T0) else s
            for i, s in enumerate(history.states)
        ),
    )
    assert victim not in active_fund_at(deck, T0, patched).injectors
    assert victim in active_fund_at(deck, T0, patched).commissioned


def test_window_excludes_wells_entering_inside_it(
    deck: DeckSchedule, history: FundHistory
) -> None:
    window = Window(start=T0, end=date(2012, 1, 1))
    at_start = active_fund_at(deck, window.start, history)
    in_window = active_fund_in_window(deck, window, history)
    assert set(in_window.injectors) <= set(at_start.injectors)
    at_end = active_fund_at(deck, date(2011, 12, 1), history)
    assert len(at_end.injectors) > len(in_window.injectors)


def test_each_window_has_its_own_wells_and_plan_width(
    deck: DeckSchedule, history: FundHistory
) -> None:
    boundaries = (T0, date(2012, 1, 1), date(2018, 1, 1), date(2025, 9, 1))
    sliced = slice_windows(deck, boundaries, history)
    assert len(sliced) == len(boundaries) - 1
    widths = [fund.plan_width for _, fund in sliced]
    assert widths[0] < widths[-1]
    assert len(set(widths)) > 1
    for window, fund in sliced:
        assert fund.when == window.start
        assert fund.plan_width == len(fund.injectors)
    first = sliced[0][1]
    last = sliced[-1][1]
    assert set(first.injectors) != set(last.injectors)


def test_plan_width_is_never_the_end_of_horizon_fund(
    deck: DeckSchedule, history: FundHistory
) -> None:
    window = Window(start=T0, end=date(2010, 1, 1))
    fund = active_fund_in_window(deck, window, history)
    assert fund.plan_width < len(active_fund_at(deck, END_OF_DECK, history).injectors)


def test_date_before_deck_start_is_rejected(deck: DeckSchedule) -> None:
    with pytest.raises(ValueError, match="раньше первой даты дека"):
        active_fund_at(deck, date(1990, 1, 1))


def test_window_boundaries_must_increase(deck: DeckSchedule, history: FundHistory) -> None:
    with pytest.raises(ValueError, match="строго возрастать"):
        slice_windows(deck, (date(2012, 1, 1), T0), history)
    with pytest.raises(ValueError, match="минимум две границы"):
        slice_windows(deck, (T0,), history)


def test_empty_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="пустое окно"):
        Window(start=T0, end=T0)


def test_date_between_deck_dates_resolves_to_previous(
    deck: DeckSchedule, history: FundHistory
) -> None:
    mid_month = date(2007, 1, 15)
    assert (
        active_fund_at(deck, mid_month, history).injectors
        == active_fund_at(deck, T0, history).injectors
    )
