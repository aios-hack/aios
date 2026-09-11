from __future__ import annotations

from collections.abc import Mapping, Sequence

from backend.contexts.constraints.domain.config import NormativeSet, Policies
from backend.contexts.economics.domain.esp import EspStateMachine
from backend.contexts.economics.domain.ledger import ProductionLedger
from backend.contexts.economics.domain.npv.terms import (
    BalanceSheetInputs,
    CellFlows,
    MONTHS_PER_YEAR,
)
from backend.contexts.reservoir.domain.response import StateAtDate


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
