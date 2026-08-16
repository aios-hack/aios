from __future__ import annotations

import math
from datetime import date

import pytest

from contracts import (
    ActiveControlMode,
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    IntervalResponse,
    NormativeSet,
    Policies,
    QuantizationPolicy,
    Schedule,
    ScheduleMeta,
    StateAtDate,
)
from economics import (
    BalanceSheetInputs,
    ESP_CATALOG_2007,
    Economics,
    EconomicsError,
    allocate_income_tax,
    annual_income_tax,
    build_cell_flows,
    build_production_ledger,
    compute_npv_table,
    discount_factor,
    load_normatives,
    monthly_income_tax_sum,
)

from conftest import missing_reason, normatives_xlsx

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)
POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.NONE,
)

NORMATIVES_XLSX = normatives_xlsx()

requires_normatives_xlsx = pytest.mark.skipif(
    NORMATIVES_XLSX is None,
    reason=missing_reason("Нормативы_ЧДД.xlsx"),
)

N_HISTORY = 2


def N_DECK_DATES_FOR(n_intervals: int) -> int:
    return N_HISTORY + n_intervals + 1


def make_state(
    deck_step: int,
    well: str,
    liquid: float = 0.0,
    injection: float = 0.0,
) -> StateAtDate:
    return StateAtDate(
        deck_date_index=deck_step,
        well=well,
        liquid_rate=liquid,
        oil_rate=liquid * 0.4,
        injection_rate=injection,
        thp=10.0,
        bhp=100.0,
        well_efficiency=1.0,
        active_control_mode=ActiveControlMode.UNKNOWN,
    )


def states(well: str, liquid_by_deck_step: list[float]) -> list[StateAtDate]:
    return [
        make_state(deck_step, well, liquid=rate)
        for deck_step, rate in enumerate(liquid_by_deck_step)
    ]


def injection_states(well: str, rate_by_deck_step: list[float]) -> list[StateAtDate]:
    return [
        make_state(deck_step, well, injection=rate)
        for deck_step, rate in enumerate(rate_by_deck_step)
    ]


def responses(
    well: str,
    oil: list[float],
    liquid: list[float] | None = None,
    injection: list[float] | None = None,
) -> list[IntervalResponse]:
    n = len(oil)
    liquid = liquid if liquid is not None else [0.0] * n
    injection = injection if injection is not None else [0.0] * n
    return [
        IntervalResponse(
            control_step=k,
            well=well,
            oil_mass_delta=oil[k],
            liquid_volume_delta=liquid[k],
            injection_volume_delta=injection[k],
        )
        for k in range(n)
    ]


def month_starts(n: int, first_year: int = 2007) -> list[date]:
    return [date(first_year + k // 12, k % 12 + 1, 1) for k in range(n)]


def evaluate(
    states_by_well: dict[str, list[StateAtDate]],
    responses_by_well: dict[str, list[IntervalResponse]],
    interval_start_dates: list[date],
    normatives: NormativeSet = NORMATIVES,
    policies: Policies = POLICIES,
    balance_sheet: BalanceSheetInputs = BalanceSheetInputs(),
):
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, normatives
    )
    return compute_npv_table(
        ledger, states_by_well, normatives, policies, balance_sheet
    )


@requires_normatives_xlsx
def test_normatives_load_from_reference_workbook() -> None:
    loaded = load_normatives(NORMATIVES_XLSX)
    assert loaded.price_oil_rub_per_t == 28_000.0
    assert loaded.deductions_rub_per_t == 19_600.0
    assert loaded.opex_oil_rub_per_t == 40.0
    assert loaded.opex_liquid_rub_per_t == 100.0
    assert loaded.opex_injection_rub_per_m3 == 30.0
    assert loaded.opex_wellstock_rub_per_well_year == 1_000_000.0
    assert loaded.esp_swap_opex_rub == 1_800_000.0
    assert loaded.event_cost_rub == 1_000_000.0
    assert loaded.conversion_base_cost_rub == 5_000_000.0
    assert loaded.wacc == pytest.approx(0.10)
    assert loaded.property_tax_rate == pytest.approx(0.022)
    assert loaded.income_tax_rate == pytest.approx(0.25)
    assert len(loaded.esp_catalog) == 12
    assert loaded.esp_catalog[0].nominal == 15.0
    assert loaded.esp_catalog[0].cost_rub == pytest.approx(550_000.0)
    assert loaded.esp_catalog[-1].nominal == 400.0
    assert loaded.esp_catalog[-1].cost_rub == pytest.approx(8_050_000.0)


@requires_normatives_xlsx
def test_normatives_loader_matches_declared_defaults() -> None:
    loaded = load_normatives(NORMATIVES_XLSX)
    for field, expected in DEFAULT_NORMATIVES_2007.items():
        assert getattr(loaded, field) == pytest.approx(expected), field


@requires_normatives_xlsx
def test_normatives_zip_fallback_matches_openpyxl() -> None:
    from economics import normatives_io

    sheets_openpyxl = normatives_io._read_sheets_via_openpyxl(NORMATIVES_XLSX)
    sheets_zip = normatives_io._read_sheets_via_zip(NORMATIVES_XLSX)
    via_openpyxl = normatives_io.parse_normative_set(sheets_openpyxl)
    via_zip = normatives_io.parse_normative_set(sheets_zip)
    assert via_zip == via_openpyxl


def test_annual_tax_differs_from_monthly_on_year_with_loss_month() -> None:
    profits = [30_000_000.0, -20_000_000.0, 10_000_000.0]
    rate = 0.25
    annual = annual_income_tax(profits, rate)
    monthly = monthly_income_tax_sum(profits, rate)
    assert annual == pytest.approx(5_000_000.0)
    assert monthly == pytest.approx(10_000_000.0)
    assert annual != pytest.approx(monthly)
    allocated = allocate_income_tax(profits, rate)
    assert sum(allocated) == pytest.approx(annual)
    assert allocated[1] == 0.0
    assert allocated[0] == pytest.approx(annual * 30 / 40)
    assert allocated[2] == pytest.approx(annual * 10 / 40)


def test_loss_year_pays_no_income_tax() -> None:
    profits = [-5_000_000.0, 1_000_000.0]
    assert annual_income_tax(profits, 0.25) == 0.0
    assert allocate_income_tax(profits, 0.25) == (0.0, 0.0)


def test_year_with_loss_month_annual_tax_below_monthly_in_table() -> None:
    n = 12
    oil = [400.0] * n
    oil[5] = 0.0
    liquid = [4000.0] * n
    liquid[5] = 60_000.0
    table = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", oil, liquid)},
        month_starts(n),
    )
    monthly_profits = [
        item.ebitda for item in (table.by_month[k] for k in sorted(table.by_month))
    ]
    assert min(monthly_profits) < 0
    year_tax = table.by_year[2007].income_tax
    naive = monthly_income_tax_sum(monthly_profits, NORMATIVES.income_tax_rate)
    assert year_tax < naive
    assert table.by_month[5].income_tax == 0.0
    assert year_tax == pytest.approx(
        max(0.0, sum(monthly_profits)) * NORMATIVES.income_tax_rate
    )


def test_property_tax_is_opex_article_and_zero_on_zero_residual() -> None:
    n = 12
    table_zero = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", [400.0] * n, [4000.0] * n)},
        month_starts(n),
    )
    assert table_zero.by_year[2007].property_tax == 0.0

    residual = 100_000_000.0
    table_taxed = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", [400.0] * n, [4000.0] * n)},
        month_starts(n),
        balance_sheet=BalanceSheetInputs(
            residual_start_rub=residual, residual_end_rub=residual
        ),
    )
    expected = residual * NORMATIVES.property_tax_rate
    year = table_taxed.by_year[2007]
    assert year.property_tax == pytest.approx(expected)
    assert year.ebitda == pytest.approx(table_zero.by_year[2007].ebitda - expected)


def test_initial_esp_is_not_capitalized() -> None:
    n = 6
    table = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", [300.0] * n, [2700.0] * n)},
        month_starts(n),
    )
    assert table.by_year[2007].capex_esp == 0.0
    assert all(table.by_month[k].capex_esp == 0.0 for k in table.by_month)


def test_esp_upsize_puts_pump_in_capex_and_operation_in_opex() -> None:
    n = 6
    rates = [90.0] * N_DECK_DATES_FOR(n)
    rates[N_HISTORY + 1 + 2] = 130.0
    table = evaluate(
        {"W1": states("W1", rates)},
        {"W1": responses("W1", [300.0] * n, [2700.0] * n)},
        month_starts(n),
    )
    assert table.by_year[2007].capex_esp == pytest.approx(2_750_000.0)
    assert table.by_month[2].capex_esp == pytest.approx(2_750_000.0)
    assert table.by_month[2].event_costs == pytest.approx(1_800_000.0)


def test_conversion_costs_exactly_five_million_without_esp() -> None:
    n = 4
    deck = N_DECK_DATES_FOR(n)
    producer_then_injector = [
        make_state(deck_step, "W1", liquid=90.0)
        if deck_step < N_HISTORY + 1 + 2
        else make_state(deck_step, "W1", injection=80.0)
        for deck_step in range(deck)
    ]
    table = evaluate(
        {"W1": producer_then_injector},
        {
            "W1": responses(
                "W1",
                [300.0, 300.0, 0.0, 0.0],
                [2700.0, 2700.0, 0.0, 0.0],
                [0.0, 0.0, 2400.0, 2400.0],
            )
        },
        month_starts(n),
    )
    assert table.by_month[2].event_costs == pytest.approx(5_000_000.0)
    assert table.by_month[2].capex_esp == 0.0
    assert table.by_year[2007].event_costs == pytest.approx(5_000_000.0)


def test_stop_costs_one_million_and_setpoint_change_is_free() -> None:
    n = 4
    deck = N_DECK_DATES_FOR(n)
    rates = [90.0] * deck
    rates[N_HISTORY + 1 + 2] = 0.0
    table = evaluate(
        {"W1": states("W1", rates)},
        {"W1": responses("W1", [300.0, 300.0, 0.0, 0.0], [2700.0, 2700.0, 0.0, 0.0])},
        month_starts(n),
    )
    assert table.by_month[2].event_costs == pytest.approx(1_000_000.0)
    assert table.by_month[3].event_costs == pytest.approx(1_000_000.0)

    varied = [90.0] * deck
    varied[N_HISTORY + 1 + 2] = 95.0
    free = evaluate(
        {"W1": states("W1", varied)},
        {"W1": responses("W1", [300.0] * n, [2700.0] * n)},
        month_starts(n),
    )
    assert free.by_year[2007].event_costs == 0.0


def test_liquid_opex_applies_to_wlpt_diff_without_density_conversion() -> None:
    n = 1
    liquid_delta = 5_000.0
    table = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", [0.0], [liquid_delta])},
        month_starts(n),
    )
    expected = liquid_delta * NORMATIVES.opex_liquid_rub_per_t
    assert table.by_month[0].opex_liquid == pytest.approx(expected)
    density = 0.85
    assert table.by_month[0].opex_liquid != pytest.approx(expected / density)
    assert table.by_month[0].opex_liquid != pytest.approx(expected * density)


def test_oil_and_injection_opex_use_own_normatives() -> None:
    n = 1
    table = evaluate(
        {
            "P1": states("P1", [90.0] * N_DECK_DATES_FOR(n)),
            "I1": injection_states("I1", [80.0] * N_DECK_DATES_FOR(n)),
        },
        {
            "P1": responses("P1", [400.0], [4000.0]),
            "I1": responses("I1", [0.0], [0.0], [3000.0]),
        },
        month_starts(n),
    )
    month = table.by_month[0]
    assert month.revenue == pytest.approx(400.0 * 28_000.0)
    assert month.deductions == pytest.approx(400.0 * 19_600.0)
    assert month.opex_oil == pytest.approx(400.0 * 40.0)
    assert month.opex_injection == pytest.approx(3000.0 * 30.0)
    assert month.opex_wellstock == pytest.approx(2 * 1_000_000.0 / 12)


def test_discount_factor_by_year_base_2007() -> None:
    assert discount_factor(2007, 0.10) == pytest.approx(1.0)
    assert discount_factor(2008, 0.10) == pytest.approx(1 / 1.1)
    assert discount_factor(2009, 0.10) == pytest.approx(1 / 1.1**2)
    assert discount_factor(2006, 0.10) == pytest.approx(1.0)

    n = 24
    table = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", [400.0] * n, [4000.0] * n)},
        month_starts(n),
    )
    assert table.by_year[2007].df == pytest.approx(1.0)
    assert table.by_year[2008].df == pytest.approx(1 / 1.1)
    assert table.by_month[0].df == pytest.approx(1.0)
    assert table.by_month[12].df == pytest.approx(1 / 1.1)
    assert table.by_year[2008].discounted_fcf == pytest.approx(
        table.by_year[2008].fcf / 1.1
    )


def test_no_own_monthly_discount_rate() -> None:
    n = 12
    table = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", [400.0] * n, [4000.0] * n)},
        month_starts(n),
    )
    assert len({table.by_month[k].df for k in table.by_month}) == 1


def test_invariant_monthly_sums_to_annual() -> None:
    n = 30
    oil = [400.0 + k for k in range(n)]
    liquid = [4000.0 + 10 * k for k in range(n)]
    oil[7] = 0.0
    liquid[7] = 40_000.0
    table = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", oil, liquid)},
        month_starts(n),
    )
    for year, annual in table.by_year.items():
        steps = [k for k in table.by_month if month_starts(n)[k].year == year]
        assert annual.discounted_fcf == pytest.approx(
            sum(table.by_month[k].discounted_fcf for k in steps), rel=0, abs=1e-6
        )
        assert annual.fcf == pytest.approx(
            sum(table.by_month[k].fcf for k in steps), rel=0, abs=1e-6
        )
        assert annual.income_tax == pytest.approx(
            sum(table.by_month[k].income_tax for k in steps), rel=0, abs=1e-6
        )
    assert table.npv_methodology == pytest.approx(
        sum(item.discounted_fcf for item in table.by_month.values()), abs=1e-6
    )


def test_invariant_per_well_sums_to_full_npv_with_tax_convention() -> None:
    n = 18
    deck = N_DECK_DATES_FOR(n)
    table = evaluate(
        {
            "P1": states("P1", [90.0] * deck),
            "P2": states("P2", [40.0] * deck),
            "I1": injection_states("I1", [80.0] * deck),
        },
        {
            "P1": responses("P1", [400.0] * n, [4000.0] * n),
            "P2": responses("P2", [120.0] * n, [1200.0] * n),
            "I1": responses("I1", [0.0] * n, [0.0] * n, [3000.0] * n),
        },
        month_starts(n),
    )
    assert sum(item.discounted_fcf for item in table.by_well.values()) == pytest.approx(
        table.npv_methodology, abs=1e-6
    )
    assert sum(item.income_tax for item in table.by_well.values()) == pytest.approx(
        sum(item.income_tax for item in table.by_year.values()), abs=1e-6
    )
    for article in ("revenue", "deductions", "opex_oil", "opex_liquid", "capex_esp"):
        assert sum(
            getattr(item, article) for item in table.by_well.values()
        ) == pytest.approx(
            sum(getattr(item, article) for item in table.by_year.values()), abs=1e-6
        )
    assert table.by_well["I1"].income_tax == 0.0
    assert all(math.isnan(item.df) for item in table.by_well.values())


def test_negative_row_is_excluded_entirely_not_zeroed() -> None:
    n = 4
    deck = N_DECK_DATES_FOR(n)
    clean = evaluate(
        {"W1": states("W1", [90.0] * deck)},
        {"W1": responses("W1", [400.0] * n, [4000.0] * n)},
        month_starts(n),
    )
    with_negative = evaluate(
        {"W1": states("W1", [90.0] * deck)},
        {
            "W1": responses(
                "W1",
                [400.0, 400.0, -1.0, 400.0],
                [4000.0, 4000.0, 4000.0, 4000.0],
            )
        },
        month_starts(n),
    )
    assert 2 not in with_negative.by_month
    assert len(with_negative.by_month) == n - 1
    assert with_negative.by_year[2007].event_costs == 0.0
    assert with_negative.by_year[2007].opex_wellstock == pytest.approx(
        clean.by_year[2007].opex_wellstock * 3 / 4
    )
    assert with_negative.by_year[2007].revenue == pytest.approx(
        clean.by_year[2007].revenue * 3 / 4
    )


def test_negative_row_does_not_charge_stop_event() -> None:
    n = 4
    deck = N_DECK_DATES_FOR(n)
    shut_deck_step = deck - n + 2
    rates = [90.0] * deck
    rates[shut_deck_step] = 0.0
    zeroed = evaluate(
        {"W1": states("W1", rates)},
        {"W1": responses("W1", [400.0, 400.0, 0.0, 400.0], [4000.0] * n)},
        month_starts(n),
    )
    excluded = evaluate(
        {"W1": states("W1", rates)},
        {"W1": responses("W1", [400.0, 400.0, -1.0, 400.0], [4000.0] * n)},
        month_starts(n),
    )
    assert zeroed.by_month[2].event_costs == pytest.approx(1_000_000.0)
    assert zeroed.by_year[2007].event_costs == pytest.approx(2_000_000.0)
    assert 2 not in excluded.by_month
    assert excluded.by_year[2007].event_costs == 0.0


def test_commissioning_inside_horizon_is_charged_as_start() -> None:
    n = 4
    deck = N_DECK_DATES_FOR(n)
    first_active_deck_step = deck - n + 2
    rates = [0.0] * deck
    for deck_step in range(first_active_deck_step, deck):
        rates[deck_step] = 90.0
    table = evaluate(
        {"W1": states("W1", rates)},
        {"W1": responses("W1", [0.0, 0.0, 400.0, 400.0], [0.0, 0.0, 4000.0, 4000.0])},
        month_starts(n),
    )
    assert table.by_year[2007].event_costs == NORMATIVES.event_cost_rub
    assert table.by_month[2].event_costs == NORMATIVES.event_cost_rub


def test_restart_after_shutdown_is_charged_as_start() -> None:
    n = 4
    deck = N_DECK_DATES_FOR(n)
    rates = [90.0] * deck
    rates[deck - n + 1] = 0.0
    table = evaluate(
        {"W1": states("W1", rates)},
        {"W1": responses("W1", [400.0, 0.0, 400.0, 400.0], [4000.0] * n)},
        month_starts(n),
    )
    assert table.by_month[1].event_costs == pytest.approx(1_000_000.0)
    assert table.by_month[2].event_costs == pytest.approx(1_000_000.0)
    assert table.by_year[2007].event_costs == pytest.approx(2_000_000.0)


def test_fcf_chain_matches_methodology() -> None:
    n = 12
    table = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", [400.0] * n, [4000.0] * n)},
        month_starts(n),
        balance_sheet=BalanceSheetInputs(
            residual_start_rub=50_000_000.0, residual_end_rub=30_000_000.0
        ),
    )
    year = table.by_year[2007]
    opex_total = (
        year.opex_oil
        + year.opex_liquid
        + year.opex_injection
        + year.opex_wellstock
        + year.property_tax
        + year.event_costs
    )
    assert year.ebitda == pytest.approx(year.revenue - opex_total - year.deductions)
    assert year.fcf == pytest.approx(year.ebitda - year.income_tax - year.capex_esp)
    assert year.discounted_fcf == pytest.approx(year.fcf * year.df)


def test_terminal_control_step_absent_from_monthly_decomposition() -> None:
    n = 5
    table = evaluate(
        {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
        {"W1": responses("W1", [400.0] * n, [4000.0] * n)},
        month_starts(n),
    )
    assert max(table.by_month) == n - 1
    assert n not in table.by_month


def test_economics_rejects_mismatched_axes() -> None:
    n = 3
    schedule = Schedule(
        meta=ScheduleMeta(n_intervals=n, wells=("W1",)),
        initial_state={},
        fixed_deck_events=(),
        control_events=(),
    )
    economics = Economics(NORMATIVES, POLICIES)
    with pytest.raises(EconomicsError):
        economics.evaluate(
            schedule,
            {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
            {"W2": responses("W2", [400.0] * n, [4000.0] * n)},
            month_starts(n),
        )
    with pytest.raises(EconomicsError):
        economics.evaluate(
            schedule,
            {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))},
            {"W1": responses("W1", [400.0] * n, [4000.0] * n)},
            month_starts(n + 1),
        )


def test_economics_evaluate_via_schedule_matches_direct_call() -> None:
    n = 6
    schedule = Schedule(
        meta=ScheduleMeta(n_intervals=n, wells=("W1",)),
        initial_state={},
        fixed_deck_events=(),
        control_events=(),
    )
    states_by_well = {"W1": states("W1", [90.0] * N_DECK_DATES_FOR(n))}
    responses_by_well = {"W1": responses("W1", [400.0] * n, [4000.0] * n)}
    dates = month_starts(n)
    economics = Economics(NORMATIVES, POLICIES)
    through_schedule = economics.evaluate(
        schedule, states_by_well, responses_by_well, dates
    )
    direct = evaluate(states_by_well, responses_by_well, dates)
    assert through_schedule.npv_methodology == pytest.approx(direct.npv_methodology)


def test_cell_flows_carry_well_axis() -> None:
    n = 3
    states_by_well = {
        "P1": states("P1", [90.0] * N_DECK_DATES_FOR(n)),
        "P2": states("P2", [40.0] * N_DECK_DATES_FOR(n)),
    }
    responses_by_well = {
        "P1": responses("P1", [400.0] * n, [4000.0] * n),
        "P2": responses("P2", [100.0] * n, [1000.0] * n),
    }
    ledger = build_production_ledger(
        states_by_well, responses_by_well, month_starts(n), NORMATIVES
    )
    flows = build_cell_flows(
        ledger, states_by_well, NORMATIVES, POLICIES, BalanceSheetInputs()
    )
    assert len(flows) == 2 * n
    assert {cell.well for cell in flows} == {"P1", "P2"}
    assert all(cell.year == 2007 for cell in flows)
