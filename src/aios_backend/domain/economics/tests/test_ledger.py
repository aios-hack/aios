from __future__ import annotations

from datetime import date

import pytest

from aios_backend.core.contracts import (
    ActiveControlMode,
    DEFAULT_NORMATIVES_2007,
    IntervalResponse,
    NormativeSet,
    StateAtDate,
)
from aios_backend.domain.economics import (
    CumulativeSeries,
    FundState,
    LedgerError,
    ProductionLedger,
    build_production_ledger,
    build_well_ledger,
    interval_responses_from_cumulative,
    interval_years,
    raw_diff,
    responses_by_well_from_cumulative,
)

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=())

N_HISTORY = 3
N_INTERVALS = 5
N_DECK_DATES = N_HISTORY + N_INTERVALS + 1


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


def prod_states(well: str = "W1", n: int = N_DECK_DATES) -> list[StateAtDate]:
    return [make_state(i, well=well, liquid=50.0) for i in range(n)]


def inj_states(well: str = "W1", n: int = N_DECK_DATES) -> list[StateAtDate]:
    return [make_state(i, well=well, injection=80.0) for i in range(n)]


def cumulative(
    well: str,
    oil_step: float,
    liquid_step: float,
    injection_step: float,
    n: int = N_DECK_DATES,
    base: float = 0.0,
) -> CumulativeSeries:
    return CumulativeSeries(
        well=well,
        oil_mass_t=tuple(base + oil_step * i for i in range(n)),
        liquid_volume_m3=tuple(base + liquid_step * i for i in range(n)),
        injection_volume_m3=tuple(base + injection_step * i for i in range(n)),
    )


def responses(
    well: str = "W1",
    oil: float = 10.0,
    liquid: float = 20.0,
    injection: float = 0.0,
    n: int = N_INTERVALS,
) -> list[IntervalResponse]:
    return [
        IntervalResponse(
            control_step=k,
            well=well,
            oil_mass_delta=oil,
            liquid_volume_delta=liquid,
            injection_volume_delta=injection,
        )
        for k in range(n)
    ]


def month_starts(n: int = N_INTERVALS, first_year: int = 2007) -> list[date]:
    return [date(first_year + k // 12, k % 12 + 1, 1) for k in range(n)]


def test_raw_diff_drops_terminal_row() -> None:
    assert raw_diff((0.0, 5.0, 12.0, 20.0)) == (5.0, 7.0, 8.0)


def test_projection_offsets_first_middle_last() -> None:
    series = CumulativeSeries(
        well="W1",
        oil_mass_t=tuple(float(i * i) for i in range(N_DECK_DATES)),
        liquid_volume_m3=tuple(float(i) for i in range(N_DECK_DATES)),
        injection_volume_m3=tuple(0.0 for _ in range(N_DECK_DATES)),
    )
    projected = interval_responses_from_cumulative(series, N_INTERVALS)
    first_interval_start = N_DECK_DATES - 1 - N_INTERVALS
    assert first_interval_start == N_HISTORY
    assert len(projected) == N_INTERVALS
    middle = N_INTERVALS // 2
    last = N_INTERVALS - 1
    for control_step in (0, middle, last):
        deck_step = first_interval_start + control_step
        expected = series.oil_mass_t[deck_step + 1] - series.oil_mass_t[deck_step]
        assert projected[control_step].oil_mass_delta == expected
        assert projected[control_step].control_step == control_step
    assert projected[last].oil_mass_delta == (
        series.oil_mass_t[N_DECK_DATES - 1] - series.oil_mass_t[N_DECK_DATES - 2]
    )


def test_well_boundary_does_not_leak_cumulative() -> None:
    high = cumulative("W1", 1.0, 2.0, 0.0, base=1_000_000.0)
    low = cumulative("W2", 1.0, 2.0, 0.0, base=0.0)
    by_well = responses_by_well_from_cumulative([high, low], N_INTERVALS)
    for well_responses in by_well.values():
        for response in well_responses:
            assert response.oil_mass_delta == 1.0
            assert response.liquid_volume_delta == 2.0
    flat = [
        response
        for well in sorted(by_well)
        for response in by_well[well]
    ]
    assert all(response.oil_mass_delta >= 0 for response in flat)
    glued = raw_diff(high.oil_mass_t + low.oil_mass_t)
    assert min(glued) < 0
    assert min(response.oil_mass_delta for response in flat) == 1.0


def test_well_boundary_rejects_duplicate_series() -> None:
    series = cumulative("W1", 1.0, 2.0, 0.0)
    with pytest.raises(LedgerError):
        responses_by_well_from_cumulative([series, series], N_INTERVALS)


def test_series_without_history_rejected() -> None:
    series = cumulative("W1", 1.0, 2.0, 0.0, n=N_INTERVALS)
    with pytest.raises(LedgerError):
        interval_responses_from_cumulative(series, N_INTERVALS)


def test_ragged_series_rejected() -> None:
    with pytest.raises(LedgerError):
        CumulativeSeries(
            well="W1",
            oil_mass_t=(0.0, 1.0),
            liquid_volume_m3=(0.0,),
            injection_volume_m3=(0.0, 1.0),
        )


def test_well_ledger_carries_volumes_and_state() -> None:
    ledger = build_well_ledger(
        "W1", prod_states(), responses(), interval_years(month_starts()), NORMATIVES
    )
    assert len(ledger.rows) == N_INTERVALS
    assert ledger.excluded_control_steps == frozenset()
    assert ledger.transitions == ()
    assert ledger.total_oil_mass_t == 10.0 * N_INTERVALS
    assert ledger.total_liquid_volume_m3 == 20.0 * N_INTERVALS
    assert ledger.total_injection_volume_m3 == 0.0
    assert all(row.fund_state is FundState.PROD_ACTIVE for row in ledger.rows)
    assert all(row.is_active for row in ledger.rows)
    assert sum(row.event_cost_rub for row in ledger.rows) == 0.0


def test_injector_gives_no_production() -> None:
    ledger = build_well_ledger(
        "W1",
        inj_states(),
        responses(oil=0.0, liquid=0.0, injection=100.0),
        interval_years(month_starts()),
        NORMATIVES,
    )
    assert ledger.total_oil_mass_t == 0.0
    assert ledger.total_liquid_volume_m3 == 0.0
    assert ledger.total_injection_volume_m3 == 100.0 * N_INTERVALS
    assert all(row.fund_state is FundState.INJ_ACTIVE for row in ledger.rows)
    assert all(row.is_active for row in ledger.rows)


def test_not_commissioned_rows_are_inactive_and_dry() -> None:
    states = [make_state(i, liquid=0.0) for i in range(N_DECK_DATES)]
    ledger = build_well_ledger(
        "W1",
        states,
        responses(oil=0.0, liquid=0.0),
        interval_years(month_starts()),
        NORMATIVES,
    )
    assert all(row.fund_state is FundState.NOT_COMMISSIONED for row in ledger.rows)
    assert not any(row.is_active for row in ledger.rows)
    assert sum(row.event_cost_rub for row in ledger.rows) == 0.0


def test_negative_row_excluded_entirely_not_zeroed() -> None:
    states = prod_states()
    for deck_step in (N_HISTORY + 3,):
        states[deck_step] = make_state(deck_step, liquid=0.0)
    rows = responses()
    rows[2] = IntervalResponse(
        control_step=2,
        well="W1",
        oil_mass_delta=10.0,
        liquid_volume_delta=-1.0,
        injection_volume_delta=0.0,
    )
    ledger = build_well_ledger(
        "W1", states, rows, interval_years(month_starts()), NORMATIVES
    )
    assert ledger.excluded_control_steps == frozenset({2})
    assert 2 not in ledger.rows_by_control_step
    assert len(ledger.rows) == N_INTERVALS - 1
    assert ledger.total_liquid_volume_m3 == 20.0 * (N_INTERVALS - 1)
    assert ledger.transitions == ()
    assert sum(row.event_cost_rub for row in ledger.rows) == 0.0
    assert all(row.is_active for row in ledger.rows)


def test_negative_row_suppresses_stop_transition_on_that_step() -> None:
    states = prod_states()
    stop_deck_step = N_HISTORY + 1 + 2
    states[stop_deck_step] = make_state(stop_deck_step, liquid=0.0)
    rows = responses()
    with_stop = build_well_ledger(
        "W1", states, rows, interval_years(month_starts()), NORMATIVES
    )
    assert [t.control_step for t in with_stop.transitions] == [2, 3]
    assert with_stop.rows_by_control_step[2].fund_state is FundState.SHUT
    assert with_stop.rows_by_control_step[2].event_cost_rub == 1_000_000.0

    rows[2] = IntervalResponse(
        control_step=2,
        well="W1",
        oil_mass_delta=-0.5,
        liquid_volume_delta=20.0,
        injection_volume_delta=0.0,
    )
    excluded = build_well_ledger(
        "W1", states, rows, interval_years(month_starts()), NORMATIVES
    )
    assert excluded.transitions == ()
    assert sum(row.event_cost_rub for row in excluded.rows) == 0.0
    assert 2 not in excluded.rows_by_control_step


def test_year_mismatch_rejected() -> None:
    with pytest.raises(LedgerError):
        build_well_ledger(
            "W1",
            prod_states(),
            responses(),
            interval_years(month_starts(n=N_INTERVALS - 1)),
            NORMATIVES,
        )


def field_ledger(n_intervals: int = 14) -> ProductionLedger:
    n_deck_dates = N_HISTORY + n_intervals + 1
    states = {
        "W1": prod_states("W1", n=n_deck_dates),
        "W2": inj_states("W2", n=n_deck_dates),
    }
    responses_by_well = {
        "W1": responses("W1", oil=10.0, liquid=20.0, injection=0.0, n=n_intervals),
        "W2": responses("W2", oil=0.0, liquid=0.0, injection=100.0, n=n_intervals),
    }
    return build_production_ledger(
        states, responses_by_well, month_starts(n=n_intervals), NORMATIVES
    )


def test_field_aggregate_over_two_years() -> None:
    ledger = field_ledger()
    assert ledger.wells == ("W1", "W2")
    assert ledger.n_intervals == 14
    by_year = ledger.by_year()
    assert sorted(by_year) == [2007, 2008]
    assert by_year[2007].oil_mass_t == 10.0 * 12
    assert by_year[2008].oil_mass_t == 10.0 * 2
    assert by_year[2007].injection_volume_m3 == 100.0 * 12
    assert by_year[2007].active_well_count == 24
    assert by_year[2008].active_well_count == 4


def test_yearly_aggregate_is_sum_of_monthly_without_remainder() -> None:
    ledger = field_ledger()
    by_month = ledger.by_control_step()
    by_year = ledger.by_year()
    for year, aggregate in by_year.items():
        months = [
            by_month[control_step]
            for control_step in by_month
            if ledger.interval_years[control_step] == year
        ]
        assert aggregate.oil_mass_t == sum(item.oil_mass_t for item in months)
        assert aggregate.liquid_volume_m3 == sum(item.liquid_volume_m3 for item in months)
        assert aggregate.injection_volume_m3 == sum(
            item.injection_volume_m3 for item in months
        )
        assert aggregate.active_well_count == sum(
            item.active_well_count for item in months
        )
        assert aggregate.event_cost_rub == sum(item.event_cost_rub for item in months)
    totals = ledger.field_totals()
    assert totals.oil_mass_t == sum(item.oil_mass_t for item in by_year.values())
    assert totals.injection_volume_m3 == sum(
        item.injection_volume_m3 for item in by_year.values()
    )
    assert totals.oil_mass_t == sum(
        ledger.by_well[well].total_oil_mass_t for well in ledger.wells
    )


def test_field_axis_mismatch_rejected() -> None:
    states = {"W1": prod_states("W1")}
    responses_by_well = {"W2": responses("W2")}
    with pytest.raises(LedgerError):
        build_production_ledger(
            states, responses_by_well, month_starts(), NORMATIVES
        )


def test_interval_count_mismatch_rejected() -> None:
    states = {"W1": prod_states("W1")}
    responses_by_well = {"W1": responses("W1", n=N_INTERVALS - 1)}
    with pytest.raises(LedgerError):
        build_production_ledger(
            states, responses_by_well, month_starts(), NORMATIVES
        )


def test_empty_field_rejected() -> None:
    with pytest.raises(LedgerError):
        build_production_ledger({}, {}, month_starts(), NORMATIVES)


def test_end_to_end_from_cumulative_matches_direct_responses() -> None:
    series = [
        cumulative("W1", 10.0, 20.0, 0.0),
        cumulative("W2", 0.0, 0.0, 100.0),
    ]
    responses_by_well = responses_by_well_from_cumulative(series, N_INTERVALS)
    states = {"W1": prod_states("W1"), "W2": inj_states("W2")}
    ledger = build_production_ledger(
        states, responses_by_well, month_starts(), NORMATIVES
    )
    assert ledger.by_well["W1"].total_oil_mass_t == 10.0 * N_INTERVALS
    assert ledger.by_well["W2"].total_injection_volume_m3 == 100.0 * N_INTERVALS
    assert ledger.by_well["W2"].total_oil_mass_t == 0.0
