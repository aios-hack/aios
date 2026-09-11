from __future__ import annotations

from collections.abc import Sequence

from backend.contexts.economics.domain.economics import NpvTable
from backend.contexts.economics.domain.decomposition.invariants import _opex_total
from backend.contexts.economics.domain.decomposition.types import (
    TaxBasis,
    WellContribution,
    WellRanking,
)
from backend.contexts.economics.domain.npv import (
    CellFlows,
    allocate_income_tax,
    discount_factor,
)


def annual_income_tax_by_well(
    flows: Sequence[CellFlows], income_tax_rate: float
) -> dict[tuple[int, str], float]:
    profits_by_year_well: dict[int, dict[str, float]] = {}
    for cell in flows:
        by_well = profits_by_year_well.setdefault(cell.year, {})
        by_well[cell.well] = by_well.get(cell.well, 0.0) + cell.taxable_profit
    allocated: dict[tuple[int, str], float] = {}
    for year, by_well in profits_by_year_well.items():
        wells = sorted(by_well)
        shares = allocate_income_tax(
            [by_well[well] for well in wells], income_tax_rate
        )
        for well, share in zip(wells, shares):
            allocated[(year, well)] = share
    return allocated


def well_contributions_from_flows(
    flows: Sequence[CellFlows],
    income_tax_rate: float,
    wacc: float,
    discount_base_year: int,
    basis: TaxBasis,
) -> WellRanking:
    tax_by_year_well = (
        annual_income_tax_by_well(flows, income_tax_rate)
        if basis is TaxBasis.WITH_ALLOCATED_TAX
        else {}
    )
    totals: dict[str, dict[str, float]] = {}
    for cell in flows:
        bucket = totals.setdefault(
            cell.well,
            {
                "revenue": 0.0,
                "opex_total": 0.0,
                "event_costs": 0.0,
                "capex_esp": 0.0,
                "income_tax": 0.0,
                "ebitda": 0.0,
                "discounted_fcf": 0.0,
            },
        )
        df = discount_factor(cell.year, wacc, discount_base_year)
        bucket["revenue"] += cell.revenue
        bucket["opex_total"] += cell.opex_total
        bucket["event_costs"] += cell.event_costs
        bucket["capex_esp"] += cell.capex_esp
        bucket["ebitda"] += cell.ebitda
        bucket["discounted_fcf"] += (cell.ebitda - cell.capex_esp) * df

    for (year, well), tax in tax_by_year_well.items():
        bucket = totals.get(well)
        if bucket is None:
            continue
        df = discount_factor(year, wacc, discount_base_year)
        bucket["income_tax"] += tax
        bucket["discounted_fcf"] -= tax * df

    contributions = tuple(
        WellContribution(
            well=well,
            basis=basis,
            revenue=bucket["revenue"],
            opex_total=bucket["opex_total"],
            event_costs=bucket["event_costs"],
            capex_esp=bucket["capex_esp"],
            income_tax=bucket["income_tax"],
            ebitda=bucket["ebitda"],
            discounted_fcf=bucket["discounted_fcf"],
        )
        for well, bucket in totals.items()
    )
    return WellRanking(
        basis=basis,
        contributions=tuple(
            sorted(contributions, key=lambda item: (item.discounted_fcf, item.well))
        ),
    )


def well_ranking(table: NpvTable) -> WellRanking:
    contributions = tuple(
        WellContribution(
            well=well,
            basis=TaxBasis.WITH_ALLOCATED_TAX,
            revenue=item.revenue,
            opex_total=_opex_total(item),
            event_costs=item.event_costs,
            capex_esp=item.capex_esp,
            income_tax=item.income_tax,
            ebitda=item.ebitda,
            discounted_fcf=item.discounted_fcf,
        )
        for well, item in table.by_well.items()
    )
    return WellRanking(
        basis=TaxBasis.WITH_ALLOCATED_TAX,
        contributions=tuple(
            sorted(contributions, key=lambda item: (item.discounted_fcf, item.well))
        ),
    )
