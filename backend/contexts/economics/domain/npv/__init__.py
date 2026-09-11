from __future__ import annotations

from backend.contexts.constraints.domain.config import (
    ChargeInitialEsp,
    NormativeSet,
    Policies,
)
from backend.contexts.economics.domain.economics import LineItems, NpvTable
from backend.contexts.economics.domain.errors import EconomicsError
from backend.contexts.economics.domain.esp import EspStateMachine
from backend.contexts.economics.domain.ledger import (
    ProductionLedger,
    build_production_ledger,
)
from backend.contexts.economics.domain.npv.cell_flows import (
    _esp_capex_by_cell,
    build_cell_flows,
)
from backend.contexts.economics.domain.npv.evaluator import Economics
from backend.contexts.economics.domain.npv.table import (
    _aggregate_cells,
    _group,
    _months_by_year,
    compute_npv_table,
    npv_table_from_flows,
)
from backend.contexts.economics.domain.npv.terms import (
    BalanceSheetInputs,
    CellFlows,
    DISCOUNT_BASE_YEAR,
    MONTHS_PER_YEAR,
    ZERO_LINE_ITEMS,
    _line_items,
    _sum_items,
    allocate_income_tax,
    annual_income_tax,
    discount_factor,
    monthly_income_tax_sum,
)
from backend.contexts.reservoir.domain.horizon import HORIZON
from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate
from backend.contexts.schedule.domain.schedule import Schedule

__all__ = [
    "BalanceSheetInputs",
    "CellFlows",
    "DISCOUNT_BASE_YEAR",
    "Economics",
    "EconomicsError",
    "MONTHS_PER_YEAR",
    "ZERO_LINE_ITEMS",
    "allocate_income_tax",
    "annual_income_tax",
    "build_cell_flows",
    "compute_npv_table",
    "discount_factor",
    "monthly_income_tax_sum",
    "npv_table_from_flows",
]
