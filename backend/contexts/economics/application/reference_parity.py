from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

from backend.contexts.constraints.domain.config import (
    ChargeInitialEsp,
    NormativeSet,
    Policies,
)
from backend.contexts.economics.application.parity_comparison import (
    Discrepancy,
    EVENT_COST_KEYS,
    LINE_ITEM_FIELDS,
    MACHINE_RELATIVE_TOLERANCE,
    ParityReport,
    REFERENCE_KEY_BY_FIELD,
    _month_index,
    compare_line_items,
    compare_with_reference,
    reference_line_items,
)
from backend.contexts.economics.domain.economics import LineItems, NpvTable
from backend.contexts.economics.domain.errors import (
    ParityError,
    ReferenceUnavailableError,
)
from backend.contexts.economics.domain.npv import BalanceSheetInputs
from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate

RUB_PER_MILLION: float = 1_000_000.0
PERCENT: float = 100.0

REFERENCE_MODULE_NAME: str = "chdd_model"
REFERENCE_FILE_NAME: str = "chdd_model.py"


def load_reference_module(chdd_python_dir: str | Path) -> ModuleType:
    root = Path(chdd_python_dir)
    module_path = root / REFERENCE_FILE_NAME
    if not module_path.is_file():
        raise ReferenceUnavailableError(
            f"reference calculator not found: {module_path}"
        )
    cached = sys.modules.get(REFERENCE_MODULE_NAME)
    if cached is not None and getattr(cached, "__file__", None) == str(module_path):
        return cached
    spec = importlib.util.spec_from_file_location(REFERENCE_MODULE_NAME, module_path)
    if spec is None or spec.loader is None:
        raise ReferenceUnavailableError(
            f"could not build a module spec from {module_path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[REFERENCE_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def deck_dates_from_interval_starts(
    interval_start_dates: Sequence[date], n_deck_dates: int
) -> tuple[date, ...]:
    n_intervals = len(interval_start_dates)
    if n_deck_dates <= n_intervals:
        raise ValueError(
            f"deck dates {n_deck_dates} are not more than the interval count {n_intervals}"
        )
    n_history = n_deck_dates - n_intervals
    dates: list[date] = []
    cursor = interval_start_dates[0]
    for _ in range(n_history):
        cursor = _previous_month_start(cursor)
        dates.append(cursor)
    dates.reverse()
    dates.extend(interval_start_dates)
    return tuple(dates)


def _previous_month_start(moment: date) -> date:
    if moment.month == 1:
        return date(moment.year - 1, 12, 1)
    return date(moment.year, moment.month - 1, 1)


def build_reference_records(
    states_by_well: Mapping[str, Sequence[StateAtDate]],
    responses_by_well: Mapping[str, Sequence[IntervalResponse]],
    interval_start_dates: Sequence[date],
    history_deltas_by_well: Mapping[str, Sequence[tuple[float, float, float]]]
    | None = None,
) -> list[dict[str, Any]]:
    if set(states_by_well) != set(responses_by_well):
        raise ValueError(
            f"well axes do not match: "
            f"{sorted(set(states_by_well) ^ set(responses_by_well))}"
        )
    n_intervals = len(interval_start_dates)
    records: list[dict[str, Any]] = []
    for well in sorted(states_by_well):
        states = states_by_well[well]
        responses = responses_by_well[well]
        if len(responses) != n_intervals:
            raise ValueError(
                f"well {well}: {len(responses)} intervals against "
                f"{n_intervals} dates"
            )
        n_deck_dates = len(states)
        deck_dates = deck_dates_from_interval_starts(
            interval_start_dates, n_deck_dates
        )
        first_interval_end_deck_step = n_deck_dates - n_intervals
        history = list(
            history_deltas_by_well.get(well, ()) if history_deltas_by_well else ()
        )
        if history and len(history) != first_interval_end_deck_step:
            raise ValueError(
                f"well {well}: {len(history)} historical increments against "
                f"{first_interval_end_deck_step} historical intervals"
            )
        cumulative_liquid = 0.0
        cumulative_oil = 0.0
        cumulative_injection = 0.0
        for deck_step, state in enumerate(states):
            liquid_delta = 0.0
            oil_delta = 0.0
            injection_delta = 0.0
            if deck_step < first_interval_end_deck_step:
                if history:
                    liquid_delta, oil_delta, injection_delta = history[deck_step]
            else:
                response = responses[deck_step - first_interval_end_deck_step]
                liquid_delta = response.liquid_volume_delta
                oil_delta = response.oil_mass_delta
                injection_delta = response.injection_volume_delta
            records.append(
                {
                    "DATA": deck_dates[deck_step].isoformat(),
                    "well": well,
                    "WLPT": cumulative_liquid,
                    "WLPR": state.liquid_rate,
                    "WOMT": cumulative_oil,
                    "WOMR": state.oil_rate,
                    "WWIR": state.injection_rate,
                    "WWIT": cumulative_injection,
                    "THP": state.thp,
                    "BHP": state.bhp,
                    "WEFF": state.well_efficiency,
                    "WLPT_Diff": liquid_delta,
                    "WOMT_Diff": oil_delta,
                    "WWIT_Diff": injection_delta,
                }
            )
            cumulative_liquid += liquid_delta
            cumulative_oil += oil_delta
            cumulative_injection += injection_delta
    return records


def reference_assumptions(
    normatives: NormativeSet,
    policies: Policies,
    balance_sheet: BalanceSheetInputs = BalanceSheetInputs(),
) -> dict[str, Any]:
    return {
        "oilPriceRubT": normatives.price_oil_rub_per_t,
        "deductionsRubT": normatives.deductions_rub_per_t,
        "oilOpexRubT": normatives.opex_oil_rub_per_t,
        "liquidOpexRubT": normatives.opex_liquid_rub_per_t,
        "injectionOpexRubM3": normatives.opex_injection_rub_per_m3,
        "fundAnnualRubWell": normatives.opex_wellstock_rub_per_well_year,
        "pumpOperationCostM": normatives.esp_swap_opex_rub / RUB_PER_MILLION,
        "profitTaxRate": normatives.income_tax_rate * PERCENT,
        "propertyTaxRate": normatives.property_tax_rate * PERCENT,
        "waccRate": normatives.wacc * PERCENT,
        "stopStartCostM": normatives.event_cost_rub / RUB_PER_MILLION,
        "conversionBaseCostM": normatives.conversion_base_cost_rub / RUB_PER_MILLION,
        "annualDepreciationM": (
            balance_sheet.annual_depreciation_rub / RUB_PER_MILLION
        ),
        "existingAssetResidualM": balance_sheet.residual_start_rub / RUB_PER_MILLION,
        "residualStartM": balance_sheet.residual_start_rub / RUB_PER_MILLION,
        "residualEndM": balance_sheet.residual_end_rub / RUB_PER_MILLION,
        "otherIncludedEbitdaM": (
            balance_sheet.other_included_ebitda_rub_per_year / RUB_PER_MILLION
        ),
        "otherExcludedEbitdaM": (
            balance_sheet.other_excluded_ebitda_rub_per_year / RUB_PER_MILLION
        ),
        "chargeInitialPump": (
            policies.charge_initial_esp is ChargeInitialEsp.CHARGED_AT_FIRST_STEP
        ),
    }


def reference_pumps(normatives: NormativeSet) -> list[dict[str, float]]:
    return [
        {
            "nominal": entry.nominal,
            "min": entry.interval_low,
            "max": entry.interval_high,
            "costM": entry.cost_rub / RUB_PER_MILLION,
        }
        for entry in normatives.esp_catalog
    ]


def run_reference(
    chdd_python_dir: str | Path,
    records: Sequence[dict[str, Any]],
    normatives: NormativeSet,
    policies: Policies,
    balance_sheet: BalanceSheetInputs = BalanceSheetInputs(),
    start_year: int | None = None,
    start_date: date | None = None,
) -> dict[str, Any]:
    if start_year is not None and start_date is not None:
        raise ValueError("Specify start_year or start_date, not both")
    module = load_reference_module(chdd_python_dir)
    calculation_start = (start_date.isoformat() if start_date is not None else
                         f"{start_year}-01-01" if start_year is not None else None)
    return module.compute_calculation(
        list(records),
        headers=list(module.REQUIRED_COLUMNS),
        assumptions=reference_assumptions(normatives, policies, balance_sheet),
        pumps=reference_pumps(normatives),
        start_date=calculation_start,
    )


__all__ = [
    "Discrepancy",
    "EVENT_COST_KEYS",
    "LINE_ITEM_FIELDS",
    "MACHINE_RELATIVE_TOLERANCE",
    "PERCENT",
    "ParityError",
    "ParityReport",
    "REFERENCE_FILE_NAME",
    "REFERENCE_KEY_BY_FIELD",
    "REFERENCE_MODULE_NAME",
    "RUB_PER_MILLION",
    "ReferenceUnavailableError",
    "build_reference_records",
    "compare_line_items",
    "compare_with_reference",
    "deck_dates_from_interval_starts",
    "load_reference_module",
    "reference_assumptions",
    "reference_line_items",
    "reference_pumps",
    "run_reference",
]
