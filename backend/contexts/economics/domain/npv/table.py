from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from backend.contexts.constraints.domain.config import NormativeSet, Policies
from backend.contexts.economics.domain.economics import LineItems, NpvTable
from backend.contexts.economics.domain.ledger import ProductionLedger
from backend.contexts.economics.domain.npv.cell_flows import build_cell_flows
from backend.contexts.economics.domain.npv.terms import (
    BalanceSheetInputs,
    CellFlows,
    DISCOUNT_BASE_YEAR,
    _line_items,
    _sum_items,
    allocate_income_tax,
    discount_factor,
)
from backend.contexts.reservoir.domain.response import StateAtDate


def _group(flows: Sequence[CellFlows], key) -> dict:
    buckets: dict = {}
    for cell in flows:
        buckets.setdefault(key(cell), []).append(cell)
    return buckets


def _months_by_year(flows: Sequence[CellFlows]) -> dict[int, dict[int, list[CellFlows]]]:
    by_year: dict[int, dict[int, list[CellFlows]]] = {}
    for cell in flows:
        by_year.setdefault(cell.year, {}).setdefault(cell.control_step, []).append(cell)
    return by_year


def compute_npv_table(
    ledger: ProductionLedger,
    states_by_well: Mapping[str, Sequence[StateAtDate]],
    normatives: NormativeSet,
    policies: Policies,
    balance_sheet: BalanceSheetInputs = BalanceSheetInputs(),
    discount_base_year: int = DISCOUNT_BASE_YEAR,
) -> NpvTable:
    flows = build_cell_flows(ledger, states_by_well, normatives, policies, balance_sheet)
    return npv_table_from_flows(flows, normatives, discount_base_year)


def npv_table_from_flows(
    flows: Sequence[CellFlows],
    normatives: NormativeSet,
    discount_base_year: int = DISCOUNT_BASE_YEAR,
) -> NpvTable:
    months_by_year = _months_by_year(flows)

    tax_by_month: dict[int, float] = {}
    tax_by_cell: dict[tuple[int, str], float] = {}
    for year, months in months_by_year.items():
        steps = sorted(months)
        profits = [
            sum(cell.taxable_profit for cell in months[step]) for step in steps
        ]
        allocated = allocate_income_tax(profits, normatives.income_tax_rate)
        for step, month_tax in zip(steps, allocated):
            tax_by_month[step] = month_tax
            month_cells = months[step]
            positive_base = sum(max(0.0, cell.taxable_profit) for cell in month_cells)
            for cell in month_cells:
                share = (
                    max(0.0, cell.taxable_profit) / positive_base
                    if positive_base > 0.0
                    else 0.0
                )
                tax_by_cell[(cell.control_step, cell.well)] = month_tax * share

    df_by_year = {
        year: discount_factor(year, normatives.wacc, discount_base_year)
        for year in months_by_year
    }

    by_month: dict[int, LineItems] = {}
    for year, months in months_by_year.items():
        df = df_by_year[year]
        for step, month_cells in months.items():
            aggregate = _aggregate_cells(month_cells)
            by_month[step] = _line_items(aggregate, tax_by_month[step], df)

    by_year: dict[int, LineItems] = {}
    for year, months in sorted(months_by_year.items()):
        by_year[year] = _sum_items([by_month[step] for step in sorted(months)])

    by_well: dict[str, LineItems] = {}
    for well, cells in sorted(_group(flows, lambda cell: cell.well).items()):
        items = [
            _line_items(
                cell,
                tax_by_cell.get((cell.control_step, cell.well), 0.0),
                df_by_year[cell.year],
            )
            for cell in cells
        ]
        by_well[well] = _sum_items(items)
        by_well[well] = replace(by_well[well], df=float("nan"))

    npv_methodology = sum(item.discounted_fcf for item in by_year.values())
    return NpvTable(
        by_year=by_year,
        by_month=dict(sorted(by_month.items())),
        by_well=by_well,
        npv_methodology=npv_methodology,
    )


def _aggregate_cells(cells: Sequence[CellFlows]) -> CellFlows:
    first = cells[0]
    return CellFlows(
        control_step=first.control_step,
        well="",
        year=first.year,
        revenue=sum(cell.revenue for cell in cells),
        deductions=sum(cell.deductions for cell in cells),
        opex_oil=sum(cell.opex_oil for cell in cells),
        opex_liquid=sum(cell.opex_liquid for cell in cells),
        opex_injection=sum(cell.opex_injection for cell in cells),
        opex_wellstock=sum(cell.opex_wellstock for cell in cells),
        property_tax=sum(cell.property_tax for cell in cells),
        event_costs=sum(cell.event_costs for cell in cells),
        capex_esp=sum(cell.capex_esp for cell in cells),
        depreciation=sum(cell.depreciation for cell in cells),
        other_included=sum(cell.other_included for cell in cells),
        other_excluded=sum(cell.other_excluded for cell in cells),
    )
