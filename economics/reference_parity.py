from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

from contracts import (
    ChargeInitialEsp,
    IntervalResponse,
    LineItems,
    NormativeSet,
    NpvTable,
    Policies,
    StateAtDate,
)

from .npv import BalanceSheetInputs

RUB_PER_MILLION: float = 1_000_000.0
PERCENT: float = 100.0

REFERENCE_MODULE_NAME: str = "chdd_model"
REFERENCE_FILE_NAME: str = "chdd_model.py"

LINE_ITEM_FIELDS: tuple[str, ...] = (
    "revenue",
    "deductions",
    "opex_oil",
    "opex_liquid",
    "opex_injection",
    "opex_wellstock",
    "property_tax",
    "event_costs",
    "capex_esp",
    "ebitda",
    "income_tax",
    "fcf",
    "df",
    "discounted_fcf",
)

REFERENCE_KEY_BY_FIELD: dict[str, str] = {
    "revenue": "revenueM",
    "deductions": "deductionsM",
    "opex_oil": "oilOpexM",
    "opex_liquid": "liquidOpexM",
    "opex_injection": "injectionOpexM",
    "opex_wellstock": "fundOpexM",
    "property_tax": "propertyTaxM",
    "capex_esp": "capexM",
    "ebitda": "ebitdaM",
    "income_tax": "profitTaxM",
    "fcf": "fcfM",
    "discounted_fcf": "chddM",
}

EVENT_COST_KEYS: tuple[str, ...] = ("gtmM", "startStopCostM", "conversionOpexM")

MACHINE_RELATIVE_TOLERANCE: float = 1e-12


class ReferenceUnavailableError(RuntimeError):
    pass


class ParityError(AssertionError):
    pass


@dataclass(frozen=True, slots=True)
class Discrepancy:
    scope: str
    key: int | str
    field: str
    ours: float
    reference: float

    @property
    def absolute(self) -> float:
        return abs(self.ours - self.reference)

    def __str__(self) -> str:
        return (
            f"{self.scope}[{self.key}].{self.field}: наш {self.ours!r} "
            f"против эталона {self.reference!r}, разница {self.absolute!r}"
        )


@dataclass(frozen=True, slots=True)
class ParityReport:
    discrepancies: tuple[Discrepancy, ...]
    npv_ours: float
    npv_reference: float
    years: tuple[int, ...]
    months: tuple[int, ...]

    @property
    def matched(self) -> bool:
        return not self.discrepancies

    @property
    def npv_absolute(self) -> float:
        return abs(self.npv_ours - self.npv_reference)

    def raise_if_mismatched(self) -> None:
        if self.matched:
            return
        head = "\n".join(str(item) for item in self.discrepancies[:20])
        raise ParityError(
            f"расхождение с эталоном: {len(self.discrepancies)} статей, "
            f"ЧДД наш {self.npv_ours!r} против {self.npv_reference!r} "
            f"(разница {self.npv_absolute!r})\n{head}"
        )


def load_reference_module(chdd_python_dir: str | Path) -> ModuleType:
    root = Path(chdd_python_dir)
    module_path = root / REFERENCE_FILE_NAME
    if not module_path.is_file():
        raise ReferenceUnavailableError(
            f"эталонный расчётчик не найден: {module_path}"
        )
    cached = sys.modules.get(REFERENCE_MODULE_NAME)
    if cached is not None and getattr(cached, "__file__", None) == str(module_path):
        return cached
    spec = importlib.util.spec_from_file_location(REFERENCE_MODULE_NAME, module_path)
    if spec is None or spec.loader is None:
        raise ReferenceUnavailableError(
            f"не удалось построить спецификацию модуля из {module_path}"
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
            f"дат дека {n_deck_dates} — не больше числа интервалов {n_intervals}"
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
            f"оси скважин не совпадают: "
            f"{sorted(set(states_by_well) ^ set(responses_by_well))}"
        )
    n_intervals = len(interval_start_dates)
    records: list[dict[str, Any]] = []
    for well in sorted(states_by_well):
        states = states_by_well[well]
        responses = responses_by_well[well]
        if len(responses) != n_intervals:
            raise ValueError(
                f"скважина {well}: {len(responses)} интервалов при "
                f"{n_intervals} датах"
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
                f"скважина {well}: {len(history)} исторических приростов при "
                f"{first_interval_end_deck_step} исторических интервалах"
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
) -> dict[str, Any]:
    module = load_reference_module(chdd_python_dir)
    start_date = f"{start_year}-01-01" if start_year is not None else None
    return module.compute_calculation(
        list(records),
        headers=list(module.REQUIRED_COLUMNS),
        assumptions=reference_assumptions(normatives, policies, balance_sheet),
        pumps=reference_pumps(normatives),
        start_date=start_date,
    )


def reference_line_items(entry: Mapping[str, Any]) -> LineItems:
    values = {
        field: float(entry[key]) * RUB_PER_MILLION
        for field, key in REFERENCE_KEY_BY_FIELD.items()
    }
    values["event_costs"] = (
        sum(float(entry[key]) for key in EVENT_COST_KEYS) * RUB_PER_MILLION
    )
    return LineItems(df=float(entry["discountFactor"]), **values)


def _month_index(month: str, interval_start_dates: Sequence[date]) -> int | None:
    for control_step, moment in enumerate(interval_start_dates):
        if f"{moment.year:04d}-{moment.month:02d}" == month:
            return control_step
    return None


def compare_line_items(
    scope: str,
    key: int | str,
    ours: LineItems,
    reference: LineItems,
    tolerance_rub: float,
    relative_tolerance: float,
) -> list[Discrepancy]:
    found: list[Discrepancy] = []
    for field in LINE_ITEM_FIELDS:
        our_value = float(getattr(ours, field))
        reference_value = float(getattr(reference, field))
        if field == "df":
            limit = 0.0
        else:
            scale = max(abs(our_value), abs(reference_value))
            limit = max(tolerance_rub, relative_tolerance * scale)
        if abs(our_value - reference_value) > limit:
            found.append(
                Discrepancy(
                    scope=scope,
                    key=key,
                    field=field,
                    ours=our_value,
                    reference=reference_value,
                )
            )
    return found


def compare_with_reference(
    table: NpvTable,
    reference_result: Mapping[str, Any],
    interval_start_dates: Sequence[date],
    tolerance_rub: float = 0.0,
    relative_tolerance: float = MACHINE_RELATIVE_TOLERANCE,
) -> ParityReport:
    discrepancies: list[Discrepancy] = []

    reference_by_year = {
        int(entry["year"]): reference_line_items(entry)
        for entry in reference_result["annual"]
    }
    our_years = tuple(sorted(table.by_year))
    reference_years = tuple(sorted(reference_by_year))
    if our_years != reference_years:
        raise ParityError(
            f"оси лет не совпадают: наши {our_years}, эталон {reference_years}"
        )
    for year in our_years:
        discrepancies.extend(
            compare_line_items(
                "год",
                year,
                table.by_year[year],
                reference_by_year[year],
                tolerance_rub,
                relative_tolerance,
            )
        )

    reference_by_step: dict[int, LineItems] = {}
    for entry in reference_result["fieldMonthly"]:
        control_step = _month_index(str(entry["month"]), interval_start_dates)
        if control_step is None:
            continue
        reference_by_step[control_step] = reference_line_items(entry)
    our_months = tuple(sorted(table.by_month))
    reference_months = tuple(sorted(reference_by_step))
    if our_months != reference_months:
        raise ParityError(
            f"оси месяцев не совпадают: наши {our_months}, "
            f"эталон {reference_months}"
        )
    for control_step in our_months:
        discrepancies.extend(
            compare_line_items(
                "месяц",
                control_step,
                table.by_month[control_step],
                reference_by_step[control_step],
                tolerance_rub,
                relative_tolerance,
            )
        )

    npv_reference = float(reference_result["summary"]["totalChddM"]) * RUB_PER_MILLION
    npv_limit = max(
        tolerance_rub,
        relative_tolerance * max(abs(table.npv_methodology), abs(npv_reference)),
    )
    if abs(table.npv_methodology - npv_reference) > npv_limit:
        discrepancies.append(
            Discrepancy(
                scope="итог",
                key="npv_methodology",
                field="npv_methodology",
                ours=table.npv_methodology,
                reference=npv_reference,
            )
        )

    return ParityReport(
        discrepancies=tuple(discrepancies),
        npv_ours=table.npv_methodology,
        npv_reference=npv_reference,
        years=our_years,
        months=our_months,
    )
