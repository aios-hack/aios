from __future__ import annotations

from datetime import date

import pytest

from aios_backend.core.contracts import IntervalResponse, N_INTERVALS, StateAtDate
from aios_backend.domain.economics import (
    BalanceSheetInputs,
    Economics,
    build_cell_flows,
    build_production_ledger,
    compute_npv_table,
)
from aios_backend.domain.economics.decomposition import (
    MACHINE_ZERO_RUB,
    DecompositionError,
    TaxBasis,
    annual_income_tax_by_well,
    check_invariants,
    decompose,
    interval_series,
    well_ranking,
)

from .test_npv import (
    NORMATIVES,
    N_DECK_DATES_FOR,
    POLICIES,
    injection_states,
    month_starts,
    responses,
    states,
)


def build(
    states_by_well: dict[str, list[StateAtDate]],
    responses_by_well: dict[str, list[IntervalResponse]],
    interval_start_dates: list[date],
    balance_sheet: BalanceSheetInputs = BalanceSheetInputs(),
):
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    table = compute_npv_table(
        ledger, states_by_well, NORMATIVES, POLICIES, balance_sheet
    )
    flows = build_cell_flows(
        ledger, states_by_well, NORMATIVES, POLICIES, balance_sheet
    )
    years = [moment.year for moment in interval_start_dates]
    return table, flows, years


def field_case(n: int = 30):
    deck = N_DECK_DATES_FOR(n)
    oil = [400.0 + k for k in range(n)]
    liquid = [4000.0 + 10 * k for k in range(n)]
    oil[7] = 0.0
    liquid[7] = 40_000.0
    rates = [90.0] * deck
    rates[deck - n + 11] = 130.0
    states_by_well = {
        "P1": states("P1", rates),
        "P2": states("P2", [40.0] * deck),
        "I1": injection_states("I1", [80.0] * deck),
    }
    responses_by_well = {
        "P1": responses("P1", oil, liquid),
        "P2": responses("P2", [120.0] * n, [1200.0] * n),
        "I1": responses("I1", [0.0] * n, [0.0] * n, [3000.0] * n),
    }
    return build(states_by_well, responses_by_well, month_starts(n))


def test_series_lives_on_intervals_not_on_control_dates() -> None:
    n = 24
    table, flows, years = field_case(n)
    series = interval_series(table, years)
    assert series.n_intervals == n
    assert series.control_steps == tuple(range(n))
    assert n not in table.by_month
    assert max(series.control_steps) == n - 1


def test_series_cumulative_ends_at_npv_methodology() -> None:
    table, flows, years = field_case()
    series = interval_series(table, years)
    assert series.points[-1].cumulative_discounted_fcf == pytest.approx(
        table.npv_methodology, abs=MACHINE_ZERO_RUB
    )
    assert series.total_discounted_fcf == pytest.approx(
        table.npv_methodology, abs=MACHINE_ZERO_RUB
    )


def test_series_uses_annual_discount_factor_only() -> None:
    n = 30
    table, flows, years = field_case(n)
    series = interval_series(table, years)
    by_year: dict[int, set[float]] = {}
    for point in series.points:
        by_year.setdefault(point.year, set()).add(point.df)
    assert all(len(values) == 1 for values in by_year.values())
    assert len(by_year) > 1
    for point in series.points:
        assert point.discounted_fcf == pytest.approx(point.fcf * point.df)


def test_invariant_monthly_sums_to_annual_at_machine_zero() -> None:
    table, flows, years = field_case()
    report = check_invariants(table, years)
    monthly = report.monthly_to_annual
    assert monthly
    assert all(
        item.within(report.absolute_tolerance, report.relative_tolerance)
        for item in monthly
    ), report.format()
    assert max(item.absolute for item in monthly) < MACHINE_ZERO_RUB


def test_invariant_per_well_sums_to_full_npv_without_remainder() -> None:
    table, flows, years = field_case()
    report = check_invariants(table, years)
    per_well = report.per_well_to_total
    assert per_well
    assert all(
        item.within(report.absolute_tolerance, report.relative_tolerance)
        for item in per_well
    ), report.format()
    total = next(item for item in per_well if item.key == "npv_methodology")
    assert total.absolute < MACHINE_ZERO_RUB
    assert total.absolute / max(1.0, abs(total.expected)) < 1e-12


def test_invariant_report_is_ok_on_a_realistic_case() -> None:
    table, flows, years = field_case()
    report = check_invariants(table, years)
    assert report.ok, report.format()
    assert "инварианты" in report.format()
    report.raise_if_violated()


def test_invariant_report_detects_a_broken_table() -> None:
    from dataclasses import replace

    table, flows, years = field_case(12)
    broken_month = replace(table.by_month[0], discounted_fcf=1.0e9)
    broken = type(table)(
        by_year=table.by_year,
        by_month={**table.by_month, 0: broken_month},
        by_well=table.by_well,
        npv_methodology=table.npv_methodology,
    )
    report = check_invariants(broken, years)
    assert not report.ok
    assert any("месячное" in item.name for item in report.failures)
    with pytest.raises(DecompositionError):
        report.raise_if_violated()


def test_income_tax_allocated_by_positive_annual_contribution() -> None:
    table, flows, years = field_case()
    allocated = annual_income_tax_by_well(flows, NORMATIVES.income_tax_rate)
    by_year: dict[int, float] = {}
    for (year, _well), tax in allocated.items():
        by_year[year] = by_year.get(year, 0.0) + tax
    for year, annual in table.by_year.items():
        assert by_year[year] == pytest.approx(annual.income_tax, abs=MACHINE_ZERO_RUB)
    assert all(tax >= 0.0 for tax in allocated.values())


def test_injector_carries_no_allocated_tax() -> None:
    table, flows, years = field_case()
    allocated = annual_income_tax_by_well(flows, NORMATIVES.income_tax_rate)
    assert all(tax == 0.0 for (_, well), tax in allocated.items() if well == "I1")


def test_both_bases_are_signed_and_differ_by_the_tax() -> None:
    table, flows, years = field_case()
    result = decompose(
        table, years, flows, NORMATIVES.income_tax_rate, NORMATIVES.wacc
    )
    before = result.ranking(TaxBasis.BEFORE_TAX)
    after = result.ranking(TaxBasis.WITH_ALLOCATED_TAX)
    assert before.basis is TaxBasis.BEFORE_TAX
    assert after.basis is TaxBasis.WITH_ALLOCATED_TAX
    assert "до налога" in before.caption
    assert "с распределённым налогом" in after.caption
    assert all(item.income_tax == 0.0 for item in before.contributions)
    assert sum(item.income_tax for item in after.contributions) == pytest.approx(
        sum(item.income_tax for item in table.by_year.values()), abs=MACHINE_ZERO_RUB
    )
    assert before.total_discounted_fcf > after.total_discounted_fcf


def test_with_allocated_tax_sums_to_npv_methodology() -> None:
    table, flows, years = field_case()
    result = decompose(
        table, years, flows, NORMATIVES.income_tax_rate, NORMATIVES.wacc
    )
    assert result.with_allocated_tax.total_discounted_fcf == pytest.approx(
        table.npv_methodology, abs=MACHINE_ZERO_RUB
    )


def test_tax_convention_does_not_reorder_positive_wells() -> None:
    table, flows, years = field_case()
    result = decompose(
        table, years, flows, NORMATIVES.income_tax_rate, NORMATIVES.wacc
    )
    before_order = [
        item.well
        for item in result.before_tax.contributions
        if item.discounted_fcf > 0.0
    ]
    after_order = [
        item.well
        for item in result.with_allocated_tax.contributions
        if item.discounted_fcf > 0.0
    ]
    assert before_order == after_order


def test_who_eats_the_money_lists_negative_wells_first() -> None:
    table, flows, years = field_case()
    result = decompose(
        table, years, flows, NORMATIVES.income_tax_rate, NORMATIVES.wacc
    )
    ranking = result.ranking(TaxBasis.BEFORE_TAX)
    values = [item.discounted_fcf for item in ranking.contributions]
    assert values == sorted(values)
    assert ranking.worst(1)[0].well == "I1"
    assert ranking.worst(1)[0].discounted_fcf < 0.0
    assert ranking.negative() == (ranking.worst(1)[0],)
    assert ranking.best(1)[0].discounted_fcf == max(values)


def test_contribution_carries_cost_articles_for_diagnosis() -> None:
    table, flows, years = field_case()
    result = decompose(
        table, years, flows, NORMATIVES.income_tax_rate, NORMATIVES.wacc
    )
    injector = next(
        item for item in result.before_tax.contributions if item.well == "I1"
    )
    assert injector.revenue == 0.0
    assert injector.opex_total > 0.0
    assert injector.ebitda < 0.0
    producer = next(
        item for item in result.before_tax.contributions if item.well == "P1"
    )
    assert producer.capex_esp > 0.0
    assert producer.revenue > 0.0


def test_well_ranking_from_table_is_the_allocated_tax_view() -> None:
    table, flows, years = field_case()
    ranking = well_ranking(table)
    assert ranking.basis is TaxBasis.WITH_ALLOCATED_TAX
    assert ranking.total_discounted_fcf == pytest.approx(
        table.npv_methodology, abs=MACHINE_ZERO_RUB
    )


def test_economics_exposes_flows_for_decomposition() -> None:
    n = 18
    deck = N_DECK_DATES_FOR(n)
    states_by_well = {"P1": states("P1", [90.0] * deck)}
    responses_by_well = {"P1": responses("P1", [400.0] * n, [4000.0] * n)}
    dates = month_starts(n)
    ledger = build_production_ledger(
        states_by_well, responses_by_well, dates, NORMATIVES
    )
    economics = Economics(NORMATIVES, POLICIES)
    table, flows = economics.evaluate_with_flows(ledger, states_by_well)
    direct = economics.evaluate_ledger(ledger, states_by_well)
    assert table.npv_methodology == pytest.approx(direct.npv_methodology)
    result = decompose(
        table,
        [moment.year for moment in dates],
        flows,
        NORMATIVES.income_tax_rate,
        NORMATIVES.wacc,
        economics.discount_base_year,
    )
    assert result.invariants.ok, result.invariants.format()
    assert result.npv_methodology == pytest.approx(table.npv_methodology)


def test_series_rejects_step_outside_interval_axis() -> None:
    table, flows, years = field_case(12)
    with pytest.raises(DecompositionError):
        interval_series(table, years[:5])


def test_full_horizon_series_has_224_intervals() -> None:
    n = N_INTERVALS
    deck = N_DECK_DATES_FOR(n)
    states_by_well = {"P1": states("P1", [90.0] * deck)}
    responses_by_well = {"P1": responses("P1", [400.0] * n, [4000.0] * n)}
    dates = month_starts(n)
    table, flows, years = build(states_by_well, responses_by_well, dates)
    result = decompose(
        table, years, flows, NORMATIVES.income_tax_rate, NORMATIVES.wacc
    )
    assert result.series.n_intervals == N_INTERVALS
    assert len(result.series.points) == N_INTERVALS
    assert result.invariants.ok, result.invariants.format()
    assert result.invariants.max_absolute < MACHINE_ZERO_RUB
    assert set(table.by_year) == set(range(2007, 2007 + (N_INTERVALS + 11) // 12))
