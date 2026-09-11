from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from backend.contexts.economics.domain.economics import LineItems, NpvTable
from backend.contexts.economics.domain.errors import BaseCaseError
from backend.contexts.economics.domain.esp import EspEventKind, EspStateMachine
from backend.contexts.economics.domain.fund import FundState
from backend.contexts.economics.domain.ledger import ProductionLedger
from backend.contexts.constraints.domain.config import NormativeSet, Policies
from backend.contexts.reservoir.domain.response import StateAtDate

RUB_PER_MILLION: float = 1_000_000.0


@dataclass(frozen=True, slots=True)
class CostStructure:
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
    discounted_fcf: float

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
    def outflow_total(self) -> float:
        return self.deductions + self.opex_total + self.capex_esp + self.income_tax

    def shares(self) -> dict[str, float]:
        total = self.outflow_total
        if total == 0.0:
            raise BaseCaseError("the cost side is zero, shares are undefined")
        return {
            "deductions": self.deductions / total,
            "opex_oil": self.opex_oil / total,
            "opex_liquid": self.opex_liquid / total,
            "opex_injection": self.opex_injection / total,
            "opex_wellstock": self.opex_wellstock / total,
            "property_tax": self.property_tax / total,
            "event_costs": self.event_costs / total,
            "capex_esp": self.capex_esp / total,
            "income_tax": self.income_tax / total,
        }


def cost_structure(items: LineItems) -> CostStructure:
    return CostStructure(
        revenue=items.revenue,
        deductions=items.deductions,
        opex_oil=items.opex_oil,
        opex_liquid=items.opex_liquid,
        opex_injection=items.opex_injection,
        opex_wellstock=items.opex_wellstock,
        property_tax=items.property_tax,
        event_costs=items.event_costs,
        capex_esp=items.capex_esp,
        ebitda=items.ebitda,
        income_tax=items.income_tax,
        fcf=items.fcf,
        discounted_fcf=items.discounted_fcf,
    )


def field_totals(table: NpvTable) -> CostStructure:
    years = sorted(table.by_year)
    if not years:
        raise BaseCaseError("the annual decomposition is empty")
    return CostStructure(
        revenue=sum(table.by_year[year].revenue for year in years),
        deductions=sum(table.by_year[year].deductions for year in years),
        opex_oil=sum(table.by_year[year].opex_oil for year in years),
        opex_liquid=sum(table.by_year[year].opex_liquid for year in years),
        opex_injection=sum(table.by_year[year].opex_injection for year in years),
        opex_wellstock=sum(table.by_year[year].opex_wellstock for year in years),
        property_tax=sum(table.by_year[year].property_tax for year in years),
        event_costs=sum(table.by_year[year].event_costs for year in years),
        capex_esp=sum(table.by_year[year].capex_esp for year in years),
        ebitda=sum(table.by_year[year].ebitda for year in years),
        income_tax=sum(table.by_year[year].income_tax for year in years),
        fcf=sum(table.by_year[year].fcf for year in years),
        discounted_fcf=sum(table.by_year[year].discounted_fcf for year in years),
    )


@dataclass(frozen=True, slots=True)
class EventTally:
    conversion_count: int
    conversion_cost_rub: float
    stop_start_count: int
    stop_start_cost_rub: float
    commissioning_count: int
    esp_swap_count: int
    esp_capex_rub: float
    esp_swap_opex_rub: float
    esp_initial_count: int

    @property
    def esp_total_rub(self) -> float:
        return self.esp_capex_rub + self.esp_swap_opex_rub

    @property
    def event_cost_total_rub(self) -> float:
        return self.conversion_cost_rub + self.stop_start_cost_rub


def tally_events(
    ledger: ProductionLedger,
    states_by_well: Mapping[str, Sequence[StateAtDate]],
    normatives: NormativeSet,
    policies: Policies,
) -> EventTally:
    conversion_count = 0
    conversion_cost = 0.0
    stop_start_count = 0
    stop_start_cost = 0.0
    commissioning_count = 0
    for well in ledger.wells:
        for transition in ledger.by_well[well].transitions:
            if transition.conversion_opex_rub > 0.0:
                conversion_count += 1
                conversion_cost += transition.conversion_opex_rub
            elif transition.previous is FundState.NOT_COMMISSIONED:
                commissioning_count += 1
                stop_start_count += 1
                stop_start_cost += transition.event_cost_rub
            elif transition.event_cost_rub > 0.0:
                stop_start_count += 1
                stop_start_cost += transition.event_cost_rub

    machine = EspStateMachine(normatives, policies.charge_initial_esp)
    n_intervals = ledger.n_intervals
    swap_count = 0
    initial_count = 0
    capex = 0.0
    swap_opex = 0.0
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
            if event.kind is EspEventKind.INITIAL:
                initial_count += 1
            else:
                swap_count += 1
            capex += event.capex_rub
            swap_opex += event.opex_rub

    return EventTally(
        conversion_count=conversion_count,
        conversion_cost_rub=conversion_cost,
        stop_start_count=stop_start_count,
        stop_start_cost_rub=stop_start_cost,
        commissioning_count=commissioning_count,
        esp_swap_count=swap_count,
        esp_capex_rub=capex,
        esp_swap_opex_rub=swap_opex,
        esp_initial_count=initial_count,
    )


@dataclass(frozen=True, slots=True)
class VolumeTotals:
    oil_mass_t: float
    liquid_volume_m3: float
    injection_volume_m3: float
    active_well_months: int


def volume_totals(ledger: ProductionLedger) -> VolumeTotals:
    aggregate = ledger.field_totals()
    return VolumeTotals(
        oil_mass_t=aggregate.oil_mass_t,
        liquid_volume_m3=aggregate.liquid_volume_m3,
        injection_volume_m3=aggregate.injection_volume_m3,
        active_well_months=aggregate.active_well_count,
    )
