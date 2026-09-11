from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.contexts.economics.domain.economics import LineItems
from backend.contexts.reservoir.domain.horizon import HORIZON

DISCOUNT_BASE_YEAR: int = HORIZON.discount_base_year
MONTHS_PER_YEAR: int = 12


ZERO_LINE_ITEMS: LineItems = LineItems(
    revenue=0.0,
    deductions=0.0,
    opex_oil=0.0,
    opex_liquid=0.0,
    opex_injection=0.0,
    opex_wellstock=0.0,
    property_tax=0.0,
    event_costs=0.0,
    capex_esp=0.0,
    ebitda=0.0,
    income_tax=0.0,
    fcf=0.0,
    df=0.0,
    discounted_fcf=0.0,
)


@dataclass(frozen=True, slots=True)
class BalanceSheetInputs:
    residual_start_rub: float = 0.0
    residual_end_rub: float = 0.0
    annual_depreciation_rub: float = 0.0
    other_included_ebitda_rub_per_year: float = 0.0
    other_excluded_ebitda_rub_per_year: float = 0.0


@dataclass(frozen=True, slots=True)
class CellFlows:
    control_step: int
    well: str
    year: int
    revenue: float
    deductions: float
    opex_oil: float
    opex_liquid: float
    opex_injection: float
    opex_wellstock: float
    property_tax: float
    event_costs: float
    capex_esp: float
    depreciation: float
    other_included: float
    other_excluded: float

    @property
    def opex_total(self) -> float:
        return (
            self.opex_oil
            + self.opex_liquid
            + self.opex_injection
            + self.opex_wellstock
            + self.property_tax
            + self.event_costs
        )

    @property
    def taxable_profit(self) -> float:
        return (
            self.revenue
            - self.opex_total
            - self.depreciation
            - self.deductions
            - self.other_included
            - self.other_excluded
        )

    @property
    def ebitda(self) -> float:
        return self.revenue - self.opex_total - self.deductions - self.other_included


def discount_factor(year: int, wacc: float, base_year: int = DISCOUNT_BASE_YEAR) -> float:
    return 1.0 / ((1.0 + wacc) ** max(0, year - base_year))


def annual_income_tax(taxable_profits: Sequence[float], rate: float) -> float:
    return max(0.0, sum(taxable_profits)) * rate


def allocate_income_tax(
    taxable_profits: Sequence[float], rate: float
) -> tuple[float, ...]:
    total_tax = annual_income_tax(taxable_profits, rate)
    positive_base = sum(max(0.0, profit) for profit in taxable_profits)
    if positive_base <= 0.0:
        return tuple(0.0 for _ in taxable_profits)
    return tuple(
        total_tax * max(0.0, profit) / positive_base for profit in taxable_profits
    )


def monthly_income_tax_sum(taxable_profits: Sequence[float], rate: float) -> float:
    return sum(max(0.0, profit) * rate for profit in taxable_profits)


def _sum_items(items: Sequence[LineItems]) -> LineItems:
    if not items:
        return ZERO_LINE_ITEMS
    return LineItems(
        revenue=sum(item.revenue for item in items),
        deductions=sum(item.deductions for item in items),
        opex_oil=sum(item.opex_oil for item in items),
        opex_liquid=sum(item.opex_liquid for item in items),
        opex_injection=sum(item.opex_injection for item in items),
        opex_wellstock=sum(item.opex_wellstock for item in items),
        property_tax=sum(item.property_tax for item in items),
        event_costs=sum(item.event_costs for item in items),
        capex_esp=sum(item.capex_esp for item in items),
        ebitda=sum(item.ebitda for item in items),
        income_tax=sum(item.income_tax for item in items),
        fcf=sum(item.fcf for item in items),
        df=items[0].df,
        discounted_fcf=sum(item.discounted_fcf for item in items),
    )


def _line_items(flows: CellFlows, income_tax: float, df: float) -> LineItems:
    ebitda = flows.ebitda
    fcf = ebitda - income_tax - flows.capex_esp
    return LineItems(
        revenue=flows.revenue,
        deductions=flows.deductions,
        opex_oil=flows.opex_oil,
        opex_liquid=flows.opex_liquid,
        opex_injection=flows.opex_injection,
        opex_wellstock=flows.opex_wellstock,
        property_tax=flows.property_tax,
        event_costs=flows.event_costs,
        capex_esp=flows.capex_esp,
        ebitda=ebitda,
        income_tax=income_tax,
        fcf=fcf,
        df=df,
        discounted_fcf=fcf * df,
    )
