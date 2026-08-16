from __future__ import annotations

import sys
from datetime import date, datetime

import pytest

from contracts import (
    ActiveControlMode,
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    IntervalResponse,
    NormativeSet,
    Policies,
    QuantizationPolicy,
    StateAtDate,
)
from economics import (
    BalanceSheetInputs,
    ESP_CATALOG_2007,
    build_production_ledger,
    compute_npv_table,
)
from economics.reference_parity import (
    ParityReport,
    build_reference_records,
    compare_with_reference,
    load_reference_module,
    run_reference,
)

from conftest import chdd_python_dir, missing_reason

CHDD_PYTHON_DIR = chdd_python_dir()

EXAMPLE_INPUT_XLSX = (
    None
    if CHDD_PYTHON_DIR is None
    else CHDD_PYTHON_DIR / "input" / "Пример_исходных_данных.xlsx"
)

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)
POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.NONE,
)

N_HISTORY = 2

pytestmark = pytest.mark.skipif(
    CHDD_PYTHON_DIR is None,
    reason=missing_reason("эталонный расчётчик CHDD_PYTHON"),
)


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
        thp=12.0,
        bhp=95.0,
        well_efficiency=1.0,
        active_control_mode=ActiveControlMode.UNKNOWN,
    )


def states(
    well: str,
    liquid_by_deck_step: list[float],
    injection_by_deck_step: list[float] | None = None,
) -> list[StateAtDate]:
    injection = injection_by_deck_step or [0.0] * len(liquid_by_deck_step)
    return [
        make_state(deck_step, well, liquid=liquid, injection=injection[deck_step])
        for deck_step, liquid in enumerate(liquid_by_deck_step)
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
            control_step=control_step,
            well=well,
            oil_mass_delta=oil[control_step],
            liquid_volume_delta=liquid[control_step],
            injection_volume_delta=injection[control_step],
        )
        for control_step in range(n)
    ]


def month_starts(n: int, first_year: int = 2007) -> list[date]:
    return [
        date(first_year + control_step // 12, control_step % 12 + 1, 1)
        for control_step in range(n)
    ]


def history_deltas(
    n_history: int = N_HISTORY,
    liquid: float = 0.0,
    oil: float = 0.0,
    injection: float = 0.0,
) -> list[tuple[float, float, float]]:
    return [(liquid, oil, injection)] * (n_history + 1)


def check_parity(
    states_by_well: dict[str, list[StateAtDate]],
    responses_by_well: dict[str, list[IntervalResponse]],
    interval_start_dates: list[date],
    history_deltas_by_well: dict[str, list[tuple[float, float, float]]] | None = None,
    normatives: NormativeSet = NORMATIVES,
    policies: Policies = POLICIES,
    balance_sheet: BalanceSheetInputs = BalanceSheetInputs(),
) -> ParityReport:
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, normatives
    )
    table = compute_npv_table(
        ledger, states_by_well, normatives, policies, balance_sheet
    )
    records = build_reference_records(
        states_by_well,
        responses_by_well,
        interval_start_dates,
        history_deltas_by_well,
    )
    reference_result = run_reference(
        CHDD_PYTHON_DIR,
        records,
        normatives,
        policies,
        balance_sheet,
        start_year=interval_start_dates[0].year,
    )
    report = compare_with_reference(table, reference_result, interval_start_dates)
    report.raise_if_mismatched()
    return report


def test_reference_module_imports_and_declares_required_columns() -> None:
    module = load_reference_module(CHDD_PYTHON_DIR)
    assert module.VERSION == "7.0.2-negative-row-filter"
    for column in ("WLPT", "WOMT", "WWIT", "WLPR", "WOMR", "WWIR", "WEFF"):
        assert column in module.REQUIRED_COLUMNS
    assert module.METHODOLOGY_LOCKS["stopStartCostM"] == 1.0
    assert module.METHODOLOGY_LOCKS["conversionBaseCostM"] == 5.0


def test_scenario_basic_two_wells_steady_production() -> None:
    n = 24
    n_deck = N_HISTORY + n + 1
    states_by_well = {
        "W1": states("W1", [90.0] * n_deck),
        "W2": states("W2", [55.0] * n_deck),
    }
    responses_by_well = {
        "W1": responses("W1", [400.0] * n, [2500.0] * n),
        "W2": responses("W2", [250.0] * n, [1600.0] * n),
    }
    report = check_parity(
        states_by_well,
        responses_by_well,
        month_starts(n),
        {
            "W1": history_deltas(N_HISTORY, 2500.0, 400.0),
            "W2": history_deltas(N_HISTORY, 1600.0, 250.0),
        },
    )
    assert report.matched
    assert report.npv_ours != 0.0


def test_scenario_year_with_loss_month_annual_tax_base() -> None:
    n = 12
    n_deck = N_HISTORY + n + 1
    oil = [400.0] * n
    oil[5] = 0.0
    liquid = [2500.0] * n
    liquid[5] = 90_000.0
    states_by_well = {"W1": states("W1", [90.0] * n_deck)}
    responses_by_well = {"W1": responses("W1", oil, liquid)}
    interval_start_dates = month_starts(n)
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    table = compute_npv_table(ledger, states_by_well, NORMATIVES, POLICIES)
    monthly_ebitda = [table.by_month[step].ebitda for step in sorted(table.by_month)]
    assert min(monthly_ebitda) < 0
    report = check_parity(
        states_by_well,
        responses_by_well,
        interval_start_dates,
        {"W1": history_deltas(N_HISTORY, 2500.0, 400.0)},
    )
    assert report.matched


def test_scenario_negative_deltas_exclude_whole_row() -> None:
    n = 12
    n_deck = N_HISTORY + n + 1
    oil = [300.0] * n
    liquid = [2000.0] * n
    liquid[7] = -50.0
    states_by_well = {"W1": states("W1", [70.0] * n_deck)}
    responses_by_well = {"W1": responses("W1", oil, liquid)}
    interval_start_dates = month_starts(n)
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    assert ledger.by_well["W1"].excluded_control_steps == frozenset({7})
    report = check_parity(
        states_by_well,
        responses_by_well,
        interval_start_dates,
        {"W1": history_deltas(N_HISTORY, 2000.0, 300.0)},
    )
    assert report.matched


def test_scenario_conversion_to_injection() -> None:
    n = 18
    n_deck = N_HISTORY + n + 1
    switch_deck_step = N_HISTORY + 6
    liquid_rates = [
        60.0 if deck_step < switch_deck_step else 0.0 for deck_step in range(n_deck)
    ]
    injection_rates = [
        0.0 if deck_step < switch_deck_step else 120.0 for deck_step in range(n_deck)
    ]
    oil = [200.0 if step < 5 else 0.0 for step in range(n)]
    liquid = [1800.0 if step < 5 else 0.0 for step in range(n)]
    injection = [0.0 if step < 5 else 3600.0 for step in range(n)]
    states_by_well = {"W1": states("W1", liquid_rates, injection_rates)}
    responses_by_well = {"W1": responses("W1", oil, liquid, injection)}
    interval_start_dates = month_starts(n)
    report = check_parity(
        states_by_well,
        responses_by_well,
        interval_start_dates,
        {"W1": history_deltas(N_HISTORY, 1800.0, 200.0)},
    )
    assert report.matched
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    table = compute_npv_table(ledger, states_by_well, NORMATIVES, POLICIES)
    assert table.by_year[2007].event_costs > 0.0


def test_scenario_stop_and_restart() -> None:
    n = 24
    n_deck = N_HISTORY + n + 1
    liquid_rates: list[float] = []
    for deck_step in range(n_deck):
        control_step = deck_step - N_HISTORY
        if 8 <= control_step < 14:
            liquid_rates.append(0.0)
        else:
            liquid_rates.append(75.0)
    oil = [300.0 if not 8 <= step < 14 else 0.0 for step in range(n)]
    liquid = [2100.0 if not 8 <= step < 14 else 0.0 for step in range(n)]
    states_by_well = {"W1": states("W1", liquid_rates)}
    responses_by_well = {"W1": responses("W1", oil, liquid)}
    report = check_parity(
        states_by_well,
        responses_by_well,
        month_starts(n),
        {"W1": history_deltas(N_HISTORY, 2100.0, 300.0)},
    )
    assert report.matched


def test_scenario_well_commissioned_inside_horizon() -> None:
    n = 24
    n_deck = N_HISTORY + n + 1
    start_deck_step = N_HISTORY + 9
    new_rates = [
        0.0 if deck_step < start_deck_step else 65.0 for deck_step in range(n_deck)
    ]
    new_oil = [0.0 if step < 9 else 280.0 for step in range(n)]
    new_liquid = [0.0 if step < 9 else 1900.0 for step in range(n)]
    states_by_well = {
        "W1": states("W1", [90.0] * n_deck),
        "NEW": states("NEW", new_rates),
    }
    responses_by_well = {
        "W1": responses("W1", [400.0] * n, [2500.0] * n),
        "NEW": responses("NEW", new_oil, new_liquid),
    }
    report = check_parity(
        states_by_well,
        responses_by_well,
        month_starts(n),
        {
            "W1": history_deltas(N_HISTORY, 2500.0, 400.0),
            "NEW": history_deltas(N_HISTORY),
        },
    )
    assert report.matched


def test_scenario_well_commissioned_exactly_on_first_control_step() -> None:
    n = 24
    n_deck = N_HISTORY + n + 1
    first_interval_deck_step = n_deck - n - 1
    new_rates = [
        0.0 if deck_step <= first_interval_deck_step else 70.0
        for deck_step in range(n_deck)
    ]
    new_oil = [0.0 if step == 0 else 290.0 for step in range(n)]
    new_liquid = [0.0 if step == 0 else 2000.0 for step in range(n)]
    states_by_well = {
        "W1": states("W1", [90.0] * n_deck),
        "NEW": states("NEW", new_rates),
    }
    responses_by_well = {
        "W1": responses("W1", [400.0] * n, [2500.0] * n),
        "NEW": responses("NEW", new_oil, new_liquid),
    }
    report = check_parity(
        states_by_well,
        responses_by_well,
        month_starts(n),
        {
            "W1": history_deltas(N_HISTORY, 2500.0, 400.0),
            "NEW": history_deltas(N_HISTORY),
        },
    )
    assert report.matched


def test_scenario_esp_upsize_with_history_before_t0() -> None:
    n = 24
    n_deck = N_HISTORY + n + 1
    liquid_rates = [60.0] * N_HISTORY
    for control_step in range(n + 1):
        if control_step < 8:
            liquid_rates.append(75.0)
        elif control_step < 16:
            liquid_rates.append(110.0)
        else:
            liquid_rates.append(140.0)
    states_by_well = {"W1": states("W1", liquid_rates)}
    responses_by_well = {
        "W1": responses("W1", [350.0] * n, [2400.0] * n),
    }
    interval_start_dates = month_starts(n)
    report = check_parity(
        states_by_well,
        responses_by_well,
        interval_start_dates,
        {"W1": history_deltas(N_HISTORY, 2400.0, 350.0)},
    )
    assert report.matched
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    table = compute_npv_table(ledger, states_by_well, NORMATIVES, POLICIES)
    assert table.by_year[2007].capex_esp > 0.0


def test_scenario_esp_downsize_below_threshold() -> None:
    n = 24
    n_deck = N_HISTORY + n + 1
    liquid_rates = [300.0] * N_HISTORY
    for control_step in range(n + 1):
        if control_step < 10:
            liquid_rates.append(330.0)
        else:
            liquid_rates.append(60.0)
    states_by_well = {"W1": states("W1", liquid_rates)}
    responses_by_well = {
        "W1": responses("W1", [500.0] * n, [6000.0] * n),
    }
    interval_start_dates = month_starts(n)
    report = check_parity(
        states_by_well,
        responses_by_well,
        interval_start_dates,
        {"W1": history_deltas(N_HISTORY, 6000.0, 500.0)},
    )
    assert report.matched
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    table = compute_npv_table(ledger, states_by_well, NORMATIVES, POLICIES)
    assert table.by_year[2007].capex_esp > 0.0
    assert table.by_month[9].capex_esp > 0.0


def test_scenario_nonzero_residual_depreciation_and_other_items() -> None:
    n = 24
    n_deck = N_HISTORY + n + 1
    balance_sheet = BalanceSheetInputs(
        residual_start_rub=800_000_000.0,
        residual_end_rub=600_000_000.0,
        annual_depreciation_rub=120_000_000.0,
        other_included_ebitda_rub_per_year=45_000_000.0,
        other_excluded_ebitda_rub_per_year=15_000_000.0,
    )
    states_by_well = {
        "W1": states("W1", [90.0] * n_deck),
        "W2": states("W2", [55.0] * n_deck),
    }
    responses_by_well = {
        "W1": responses("W1", [400.0] * n, [2500.0] * n),
        "W2": responses("W2", [250.0] * n, [1600.0] * n),
    }
    interval_start_dates = month_starts(n)
    report = check_parity(
        states_by_well,
        responses_by_well,
        interval_start_dates,
        {
            "W1": history_deltas(N_HISTORY, 2500.0, 400.0),
            "W2": history_deltas(N_HISTORY, 1600.0, 250.0),
        },
        balance_sheet=balance_sheet,
    )
    assert report.matched
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    table = compute_npv_table(
        ledger, states_by_well, NORMATIVES, POLICIES, balance_sheet
    )
    assert table.by_year[2007].property_tax > 0.0


def test_scenario_charged_initial_esp_option() -> None:
    n = 12
    n_deck = N_HISTORY + n + 1
    policies = Policies(
        charge_initial_esp=ChargeInitialEsp.CHARGED_AT_FIRST_STEP,
        quantization_policy=QuantizationPolicy.NONE,
    )
    states_by_well = {"W1": states("W1", [90.0] * n_deck)}
    responses_by_well = {"W1": responses("W1", [400.0] * n, [2500.0] * n)}
    report = check_parity(
        states_by_well,
        responses_by_well,
        month_starts(n),
        {"W1": history_deltas(N_HISTORY, 2500.0, 400.0)},
        policies=policies,
    )
    assert report.matched


def load_example_input() -> tuple[
    dict[str, list[StateAtDate]],
    dict[str, list[IntervalResponse]],
    list[date],
    list[dict[str, object]],
]:
    sys.path.insert(0, str(CHDD_PYTHON_DIR))
    from excel_io import load_source_records

    _, records = load_source_records(EXAMPLE_INPUT_XLSX)
    rows_by_well: dict[str, list[tuple[date, dict[str, object]]]] = {}
    for record in records:
        raw = record["DATA"]
        moment = raw.date() if isinstance(raw, datetime) else raw
        rows_by_well.setdefault(str(record["well"]), []).append((moment, record))
    for rows in rows_by_well.values():
        rows.sort(key=lambda item: item[0])
    deck_dates = sorted({moment for rows in rows_by_well.values() for moment, _ in rows})
    n_intervals = len(deck_dates) - 1
    interval_start_dates = deck_dates[1:]
    states_by_well: dict[str, list[StateAtDate]] = {}
    responses_by_well: dict[str, list[IntervalResponse]] = {}
    for well, rows in rows_by_well.items():
        row_by_date = {moment: record for moment, record in rows}
        states_by_well[well] = [
            StateAtDate(
                deck_date_index=index,
                well=well,
                liquid_rate=float(row_by_date[moment]["WLPR"]),
                oil_rate=float(row_by_date[moment]["WOMR"]),
                injection_rate=float(row_by_date[moment]["WWIR"]),
                thp=float(row_by_date[moment]["THP"]),
                bhp=float(row_by_date[moment]["BHP"]),
                well_efficiency=float(row_by_date[moment]["WEFF"]),
                active_control_mode=ActiveControlMode.UNKNOWN,
            )
            for index, moment in enumerate(deck_dates)
        ]
        responses_by_well[well] = [
            IntervalResponse(
                control_step=control_step,
                well=well,
                oil_mass_delta=float(row_by_date[deck_dates[control_step + 1]]["WOMT_Diff"]),
                liquid_volume_delta=float(
                    row_by_date[deck_dates[control_step + 1]]["WLPT_Diff"]
                ),
                injection_volume_delta=float(
                    row_by_date[deck_dates[control_step + 1]]["WWIT_Diff"]
                ),
            )
            for control_step in range(n_intervals)
        ]
    return states_by_well, responses_by_well, interval_start_dates, records


def test_external_example_input_matches_reference_on_organizer_data() -> None:
    # Вход эталона читается его же `excel_io`, а тот держится на openpyxl
    # жёстко: stdlib-обхода, как в нашем normatives_io, у организаторов нет.
    pytest.importorskip(
        "openpyxl",
        reason="excel_io организаторов читает Пример_исходных_данных.xlsx только через openpyxl",
    )
    states_by_well, responses_by_well, interval_start_dates, records = (
        load_example_input()
    )
    start_year = interval_start_dates[0].year
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    table = compute_npv_table(
        ledger,
        states_by_well,
        NORMATIVES,
        POLICIES,
        BalanceSheetInputs(),
        discount_base_year=start_year,
    )
    reference_result = run_reference(
        CHDD_PYTHON_DIR, records, NORMATIVES, POLICIES, start_year=start_year
    )
    report = compare_with_reference(table, reference_result, interval_start_dates)
    report.raise_if_mismatched()
    assert report.years == (2014, 2015)
    assert report.npv_ours == pytest.approx(
        float(reference_result["summary"]["totalChddM"]) * 1_000_000.0, rel=1e-12
    )


def test_parity_report_detects_injected_discrepancy() -> None:
    from dataclasses import replace

    n = 12
    n_deck = N_HISTORY + n + 1
    states_by_well = {"W1": states("W1", [90.0] * n_deck)}
    responses_by_well = {"W1": responses("W1", [400.0] * n, [2500.0] * n)}
    interval_start_dates = month_starts(n)
    ledger = build_production_ledger(
        states_by_well, responses_by_well, interval_start_dates, NORMATIVES
    )
    table = compute_npv_table(ledger, states_by_well, NORMATIVES, POLICIES)
    records = build_reference_records(
        states_by_well,
        responses_by_well,
        interval_start_dates,
        {"W1": history_deltas(N_HISTORY, 2500.0, 400.0)},
    )
    reference_result = run_reference(
        CHDD_PYTHON_DIR, records, NORMATIVES, POLICIES, start_year=2007
    )
    spoiled = replace(
        table,
        by_year={
            year: replace(item, revenue=item.revenue + 1.0)
            for year, item in table.by_year.items()
        },
    )
    report = compare_with_reference(spoiled, reference_result, interval_start_dates)
    assert not report.matched
    assert any(item.field == "revenue" for item in report.discrepancies)
    with pytest.raises(AssertionError):
        report.raise_if_mismatched()
