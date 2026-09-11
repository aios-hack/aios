from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.contexts.economics.domain.economics import NpvTable
from backend.contexts.economics.domain.decomposition.contributions import (
    well_contributions_from_flows,
    well_ranking,
)
from backend.contexts.economics.domain.decomposition.invariants import (
    check_invariants,
    interval_series,
)
from backend.contexts.economics.domain.decomposition.types import (
    InvariantReport,
    IntervalSeries,
    MACHINE_RELATIVE_TOLERANCE,
    MACHINE_ZERO_RUB,
    TaxBasis,
    WellRanking,
)
from backend.contexts.economics.domain.npv import CellFlows, DISCOUNT_BASE_YEAR


@dataclass(frozen=True, slots=True)
class NpvDecomposition:
    table: NpvTable
    series: IntervalSeries
    invariants: InvariantReport
    before_tax: WellRanking
    with_allocated_tax: WellRanking

    @property
    def npv_methodology(self) -> float:
        return self.table.npv_methodology

    def ranking(self, basis: TaxBasis) -> WellRanking:
        return (
            self.before_tax
            if basis is TaxBasis.BEFORE_TAX
            else self.with_allocated_tax
        )


def decompose(
    table: NpvTable,
    interval_years: Sequence[int],
    flows: Sequence[CellFlows],
    income_tax_rate: float,
    wacc: float,
    discount_base_year: int = DISCOUNT_BASE_YEAR,
    absolute_tolerance: float = MACHINE_ZERO_RUB,
    relative_tolerance: float = MACHINE_RELATIVE_TOLERANCE,
) -> NpvDecomposition:
    before_tax = well_contributions_from_flows(
        flows, income_tax_rate, wacc, discount_base_year, TaxBasis.BEFORE_TAX
    )
    with_allocated_tax = well_contributions_from_flows(
        flows,
        income_tax_rate,
        wacc,
        discount_base_year,
        TaxBasis.WITH_ALLOCATED_TAX,
    )
    return NpvDecomposition(
        table=table,
        series=interval_series(table, interval_years),
        invariants=check_invariants(
            table, interval_years, absolute_tolerance, relative_tolerance
        ),
        before_tax=before_tax,
        with_allocated_tax=with_allocated_tax,
    )
