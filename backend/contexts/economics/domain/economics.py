from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LineItems:

    revenue: float
    deductions: float
    opex_oil: float
    opex_liquid: float
    opex_injection: float
    opex_wellstock: float
    property_tax: float
    event_costs: float
    capex_esp: float
    ebitda: float
    income_tax: float
    fcf: float
    df: float
    discounted_fcf: float


@dataclass(frozen=True, slots=True)
class NpvTable:

    by_year: dict[int, LineItems]
    by_month: dict[int, LineItems]
    by_well: dict[str, LineItems]
    npv_methodology: float
