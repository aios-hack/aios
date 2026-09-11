from __future__ import annotations

from backend.contexts.economics.domain.economics import LineItems, NpvTable
from backend.contexts.economics.domain.errors import DecompositionError
from backend.contexts.economics.domain.decomposition.contributions import (
    annual_income_tax_by_well,
    well_contributions_from_flows,
    well_ranking,
)
from backend.contexts.economics.domain.decomposition.invariants import (
    EXACT_PER_WELL_FIELDS,
    _opex_total,
    check_invariants,
    check_monthly_to_annual,
    check_per_well_to_total,
    interval_series,
)
from backend.contexts.economics.domain.decomposition.report import (
    NpvDecomposition,
    decompose,
)
from backend.contexts.economics.domain.decomposition.types import (
    IntervalPoint,
    IntervalSeries,
    InvariantReport,
    InvariantResidual,
    MACHINE_RELATIVE_TOLERANCE,
    MACHINE_ZERO_RUB,
    TAX_BASIS_CAPTION,
    TaxBasis,
    WellContribution,
    WellRanking,
)
from backend.contexts.economics.domain.npv import (
    CellFlows,
    DISCOUNT_BASE_YEAR,
    allocate_income_tax,
    discount_factor,
)

__all__ = [
    "DecompositionError",
    "EXACT_PER_WELL_FIELDS",
    "IntervalPoint",
    "IntervalSeries",
    "InvariantReport",
    "InvariantResidual",
    "MACHINE_RELATIVE_TOLERANCE",
    "MACHINE_ZERO_RUB",
    "NpvDecomposition",
    "TAX_BASIS_CAPTION",
    "TaxBasis",
    "WellContribution",
    "WellRanking",
    "annual_income_tax_by_well",
    "check_invariants",
    "check_monthly_to_annual",
    "check_per_well_to_total",
    "decompose",
    "interval_series",
    "well_contributions_from_flows",
    "well_ranking",
]
