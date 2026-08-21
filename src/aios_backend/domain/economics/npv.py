from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from aios_backend.core.contracts import (
    ChargeInitialEsp,
    IntervalResponse,
    LineItems,
    NormativeSet,
    NpvTable,
    Policies,
    Schedule,
    StateAtDate,
)

from .esp import EspStateMachine
from .ledger import ProductionLedger, build_production_ledger

DISCOUNT_BASE_YEAR: int = 2007
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


class EconomicsError(ValueError):
    pass


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


def _esp_capex_by_cell(
    ledger: ProductionLedger,
    states_by_well: Mapping[str, Sequence[StateAtDate]],
    normatives: NormativeSet,
    policies: Policies,
) -> tuple[dict[tuple[int, str], float], dict[tuple[int, str], float]]:
    machine = EspStateMachine(normatives, policies.charge_initial_esp)
    capex: dict[tuple[int, str], float] = {}
    swap_opex: dict[tuple[int, str], float] = {}
    n_intervals = ledger.n_intervals
    for well in ledger.wells:
        states = states_by_well[well]
        first_interval_end_deck_step = len(states) - n_intervals
        excluded_deck_steps = frozenset(
            first_interval_end_deck_step + control_step
            for control_step in ledger.by_well[well].excluded_control_steps
        )
        track = machine.track_well(well, states, n_intervals, excluded_deck_steps)
        for event in track.events:
            control_step = event.deck_step - first_interval_end_deck_step
            if not (0 <= control_step < n_intervals):
                continue
            key = (control_step, well)
            capex[key] = capex.get(key, 0.0) + event.capex_rub
            swap_opex[key] = swap_opex.get(key, 0.0) + event.opex_rub
    return capex, swap_opex


def build_cell_flows(
    ledger: ProductionLedger,
    states_by_well: Mapping[str, Sequence[StateAtDate]],
    normatives: NormativeSet,
    policies: Policies,
    balance_sheet: BalanceSheetInputs,
) -> tuple[CellFlows, ...]:
    capex_by_cell, swap_opex_by_cell = _esp_capex_by_cell(
        ledger, states_by_well, normatives, policies
    )
    months_in_year: dict[int, int] = {}
    for year in ledger.by_year():
        months_in_year[year] = 0
    for control_step, year in enumerate(ledger.interval_years):
        months_in_year[year] = months_in_year.get(year, 0) + 1
    active_cells_in_month: dict[int, int] = {}
    rows_in_month: dict[int, int] = {}
    for row in ledger.rows:
        rows_in_month[row.control_step] = rows_in_month.get(row.control_step, 0) + 1
        if row.is_active:
            active_cells_in_month[row.control_step] = (
                active_cells_in_month.get(row.control_step, 0) + 1
            )

    monthly_property_tax = (
        (balance_sheet.residual_start_rub + balance_sheet.residual_end_rub)
        / 2.0
        * normatives.property_tax_rate
        / MONTHS_PER_YEAR
    )
    monthly_depreciation = balance_sheet.annual_depreciation_rub / MONTHS_PER_YEAR
    monthly_other_included = (
        balance_sheet.other_included_ebitda_rub_per_year / MONTHS_PER_YEAR
    )
    monthly_other_excluded = (
        balance_sheet.other_excluded_ebitda_rub_per_year / MONTHS_PER_YEAR
    )

    flows: list[CellFlows] = []
    for row in ledger.rows:
        key = (row.control_step, row.well)
        active_cells = active_cells_in_month.get(row.control_step, 0)
        if active_cells:
            field_share = 1.0 / active_cells if row.is_active else 0.0
        else:
            field_share = 1.0 / rows_in_month[row.control_step]
        flows.append(
            CellFlows(
                control_step=row.control_step,
                well=row.well,
                year=row.year,
                revenue=row.oil_mass_t * normatives.price_oil_rub_per_t,
                deductions=row.oil_mass_t * normatives.deductions_rub_per_t,
                opex_oil=row.oil_mass_t * normatives.opex_oil_rub_per_t,
                opex_liquid=row.liquid_volume_m3 * normatives.opex_liquid_rub_per_t,
                opex_injection=(
                    row.injection_volume_m3 * normatives.opex_injection_rub_per_m3
                ),
                opex_wellstock=(
                    normatives.opex_wellstock_rub_per_well_year / MONTHS_PER_YEAR
                    if row.is_active
                    else 0.0
                ),
                property_tax=monthly_property_tax * field_share,
                event_costs=row.event_cost_rub + swap_opex_by_cell.get(key, 0.0),
                capex_esp=capex_by_cell.get(key, 0.0),
                depreciation=monthly_depreciation * field_share,
                other_included=monthly_other_included * field_share,
                other_excluded=monthly_other_excluded * field_share,
            )
        )
    return tuple(flows)


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


class Economics:
    def __init__(
        self,
        normatives: NormativeSet,
        policies: Policies,
        balance_sheet: BalanceSheetInputs = BalanceSheetInputs(),
        discount_base_year: int = DISCOUNT_BASE_YEAR,
    ) -> None:
        self._normatives = normatives
        self._policies = policies
        self._balance_sheet = balance_sheet
        self._discount_base_year = discount_base_year

    @property
    def normatives(self) -> NormativeSet:
        return self._normatives

    @property
    def policies(self) -> Policies:
        return self._policies

    def evaluate(
        self,
        schedule: Schedule,
        states_by_well: Mapping[str, Sequence[StateAtDate]],
        responses_by_well: Mapping[str, Sequence[IntervalResponse]],
        interval_start_dates: Sequence[date],
    ) -> NpvTable:
        if schedule.meta.n_intervals != len(interval_start_dates):
            raise EconomicsError(
                f"расписание объявляет {schedule.meta.n_intervals} интервалов, "
                f"дат интервалов {len(interval_start_dates)}"
            )
        wells = set(states_by_well)
        if wells != set(responses_by_well):
            raise EconomicsError(
                f"оси скважин отклика не совпадают: "
                f"{sorted(wells ^ set(responses_by_well))}"
            )
        if schedule.initial_state and set(schedule.initial_state) != wells:
            raise EconomicsError(
                f"ось скважин расписания не совпадает с осью отклика: "
                f"{sorted(set(schedule.initial_state) ^ wells)}"
            )
        ledger = build_production_ledger(
            states_by_well,
            responses_by_well,
            interval_start_dates,
            self._normatives,
        )
        return self.evaluate_ledger(ledger, states_by_well)

    def evaluate_ledger(
        self,
        ledger: ProductionLedger,
        states_by_well: Mapping[str, Sequence[StateAtDate]],
    ) -> NpvTable:
        return compute_npv_table(
            ledger,
            states_by_well,
            self._normatives,
            self._policies,
            self._balance_sheet,
            self._discount_base_year,
        )

    def evaluate_with_flows(
        self,
        ledger: ProductionLedger,
        states_by_well: Mapping[str, Sequence[StateAtDate]],
    ) -> tuple[NpvTable, tuple[CellFlows, ...]]:
        flows = build_cell_flows(
            ledger,
            states_by_well,
            self._normatives,
            self._policies,
            self._balance_sheet,
        )
        table = npv_table_from_flows(flows, self._normatives, self._discount_base_year)
        return table, flows

    @property
    def discount_base_year(self) -> int:
        return self._discount_base_year
