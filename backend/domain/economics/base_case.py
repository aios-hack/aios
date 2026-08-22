from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from backend.core.contracts import (
    ActiveControlMode,
    IntervalResponse,
    LineItems,
    NormativeSet,
    NpvTable,
    Policies,
    ResponseArtifact,
    StateAtDate,
)

from .decomposition import (
    NpvDecomposition,
    TaxBasis,
    WellRanking,
    decompose,
)
from .esp import EspEventKind, EspStateMachine
from .fund import FundState
from .ledger import ProductionLedger, build_production_ledger
from .npv import BalanceSheetInputs, CellFlows, Economics

RUB_PER_MILLION: float = 1_000_000.0


class BaseCaseError(ValueError):
    pass


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
            raise BaseCaseError("расходная часть нулевая, доли не определены")
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
        raise BaseCaseError("годовое разложение пусто")
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


@dataclass(frozen=True, slots=True)
class BaseCaseAnalysis:
    source_run_id: str
    response_hash: str
    n_wells: int
    n_deck_dates: int
    n_intervals: int
    interval_start_dates: tuple[date, ...]
    excluded_row_count: int
    excluded_dates: tuple[date, ...]
    table: NpvTable
    decomposition: NpvDecomposition
    flows: tuple[CellFlows, ...]
    totals: CostStructure
    events: EventTally
    volumes: VolumeTotals

    @property
    def npv_methodology(self) -> float:
        return self.table.npv_methodology

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(sorted(self.table.by_year))

    def structure_by_year(self) -> dict[int, CostStructure]:
        return {
            year: cost_structure(self.table.by_year[year]) for year in self.years
        }

    def ranking(self, basis: TaxBasis) -> WellRanking:
        return self.decomposition.ranking(basis)

    def loss_making_wells(self, basis: TaxBasis = TaxBasis.BEFORE_TAX):
        return self.ranking(basis).negative()


def states_by_well_from_artifact(
    artifact: ResponseArtifact,
) -> dict[str, tuple[StateAtDate, ...]]:
    grouped: dict[str, list[StateAtDate]] = {}
    for state in artifact.state_at_date:
        grouped.setdefault(state.well, []).append(state)
    return {
        well: tuple(sorted(states, key=lambda item: item.deck_date_index))
        for well, states in grouped.items()
    }


def responses_by_well_from_artifact(
    artifact: ResponseArtifact,
) -> dict[str, tuple[IntervalResponse, ...]]:
    grouped: dict[str, list[IntervalResponse]] = {}
    for response in artifact.interval_response:
        grouped.setdefault(response.well, []).append(response)
    return {
        well: tuple(sorted(items, key=lambda item: item.control_step))
        for well, items in grouped.items()
    }


def interval_start_dates(
    deck_dates: Sequence[date], t0_deck_date_index: int, n_intervals: int
) -> tuple[date, ...]:
    if t0_deck_date_index + n_intervals > len(deck_dates):
        raise BaseCaseError(
            f"дат дека {len(deck_dates)} не хватает на {n_intervals} интервалов "
            f"от t0_deck_date_index={t0_deck_date_index}"
        )
    return tuple(
        deck_dates[t0_deck_date_index + control_step]
        for control_step in range(n_intervals)
    )


def analyze_base_case(
    artifact: ResponseArtifact,
    deck_dates: Sequence[date],
    t0_deck_date_index: int,
    normatives: NormativeSet,
    policies: Policies,
    balance_sheet: BalanceSheetInputs = BalanceSheetInputs(),
) -> BaseCaseAnalysis:
    states_by_well = states_by_well_from_artifact(artifact)
    responses_by_well = responses_by_well_from_artifact(artifact)
    if set(states_by_well) != set(responses_by_well):
        raise BaseCaseError(
            f"оси скважин отклика не совпадают: "
            f"{sorted(set(states_by_well) ^ set(responses_by_well))}"
        )
    if not states_by_well:
        raise BaseCaseError("отклик не содержит ни одной скважины")

    n_deck_dates_by_well = {len(states) for states in states_by_well.values()}
    if len(n_deck_dates_by_well) != 1:
        raise BaseCaseError(
            f"скважины несут разное число дат дека: {sorted(n_deck_dates_by_well)}"
        )
    n_intervals_by_well = {len(items) for items in responses_by_well.values()}
    if len(n_intervals_by_well) != 1:
        raise BaseCaseError(
            f"скважины несут разное число интервалов: {sorted(n_intervals_by_well)}"
        )
    n_deck_dates = n_deck_dates_by_well.pop()
    n_intervals = n_intervals_by_well.pop()
    if len(deck_dates) != n_deck_dates:
        raise BaseCaseError(
            f"дат дека {len(deck_dates)}, отклик размечен на {n_deck_dates}"
        )

    starts = interval_start_dates(deck_dates, t0_deck_date_index, n_intervals)
    ledger = build_production_ledger(
        states_by_well, responses_by_well, starts, normatives
    )
    economics = Economics(normatives, policies, balance_sheet)
    table, flows = economics.evaluate_with_flows(ledger, states_by_well)
    decomposition = decompose(
        table,
        ledger.interval_years,
        flows,
        normatives.income_tax_rate,
        normatives.wacc,
        economics.discount_base_year,
    )

    excluded_steps: list[int] = []
    for well in ledger.wells:
        excluded_steps.extend(ledger.by_well[well].excluded_control_steps)
    excluded_dates = tuple(sorted({starts[step] for step in excluded_steps}))

    return BaseCaseAnalysis(
        source_run_id=artifact.source_run_id,
        response_hash=artifact.response_hash,
        n_wells=len(states_by_well),
        n_deck_dates=n_deck_dates,
        n_intervals=n_intervals,
        interval_start_dates=starts,
        excluded_row_count=len(excluded_steps),
        excluded_dates=excluded_dates,
        table=table,
        decomposition=decomposition,
        flows=flows,
        totals=field_totals(table),
        events=tally_events(ledger, states_by_well, normatives, policies),
        volumes=volume_totals(ledger),
    )


def save_response_artifact(artifact: ResponseArtifact, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_run_id": artifact.source_run_id,
        "response_hash": artifact.response_hash,
        "state_at_date": [
            {
                "deck_date_index": state.deck_date_index,
                "well": state.well,
                "liquid_rate": state.liquid_rate,
                "oil_rate": state.oil_rate,
                "injection_rate": state.injection_rate,
                "thp": state.thp,
                "bhp": state.bhp,
                "well_efficiency": state.well_efficiency,
                "active_control_mode": state.active_control_mode.value,
            }
            for state in artifact.state_at_date
        ],
        "interval_response": [
            {
                "control_step": response.control_step,
                "well": response.well,
                "oil_mass_delta": response.oil_mass_delta,
                "liquid_volume_delta": response.liquid_volume_delta,
                "injection_volume_delta": response.injection_volume_delta,
            }
            for response in artifact.interval_response
        ],
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)
    return target


def load_response_artifact(path: Path | str) -> ResponseArtifact:
    source = Path(path)
    if not source.is_file():
        raise BaseCaseError(
            f"артефакт отклика базового прогона не найден: {source}. "
            "Получается настоящим прогоном OPM "
            "(`bridge.run_base_case` → `save_response_artifact`), синтетикой не подменяется."
        )
    payload = json.loads(source.read_text(encoding="utf-8"))
    return ResponseArtifact(
        source_run_id=payload["source_run_id"],
        response_hash=payload["response_hash"],
        state_at_date=tuple(
            StateAtDate(
                deck_date_index=item["deck_date_index"],
                well=item["well"],
                liquid_rate=item["liquid_rate"],
                oil_rate=item["oil_rate"],
                injection_rate=item["injection_rate"],
                thp=item["thp"],
                bhp=item["bhp"],
                well_efficiency=item["well_efficiency"],
                active_control_mode=ActiveControlMode(item["active_control_mode"]),
            )
            for item in payload["state_at_date"]
        ),
        interval_response=tuple(
            IntervalResponse(
                control_step=item["control_step"],
                well=item["well"],
                oil_mass_delta=item["oil_mass_delta"],
                liquid_volume_delta=item["liquid_volume_delta"],
                injection_volume_delta=item["injection_volume_delta"],
            )
            for item in payload["interval_response"]
        ),
    )


def format_report(analysis: BaseCaseAnalysis) -> str:
    lines: list[str] = []
    lines.append("ЭКОНОМИЧЕСКИЙ РАЗБОР БАЗОВОГО СЦЕНАРИЯ")
    lines.append(f"прогон {analysis.source_run_id}, отклик {analysis.response_hash[:16]}")
    lines.append(
        f"скважин {analysis.n_wells}, дат дека {analysis.n_deck_dates}, "
        f"интервалов {analysis.n_intervals}"
    )
    lines.append(
        f"исключено строк по правилу отрицательного прироста: "
        f"{analysis.excluded_row_count}, даты {[str(d) for d in analysis.excluded_dates]}"
    )
    lines.append("")
    lines.append(
        f"ЧДД по Методике: {analysis.npv_methodology / RUB_PER_MILLION:.3f} млн руб"
    )
    lines.append("")

    volumes = analysis.volumes
    lines.append(
        f"нефть {volumes.oil_mass_t / 1000.0:.1f} тыс. т, "
        f"жидкость {volumes.liquid_volume_m3 / 1000.0:.1f} тыс. м³, "
        f"закачка {volumes.injection_volume_m3 / 1000.0:.1f} тыс. м³"
    )
    lines.append("")

    totals = analysis.totals
    lines.append("СТРУКТУРА, млн руб за горизонт (недисконтированная)")
    for caption, value in (
        ("выручка", totals.revenue),
        ("отчисления", totals.deductions),
        ("OPEX нефть", totals.opex_oil),
        ("OPEX жидкость", totals.opex_liquid),
        ("OPEX закачка", totals.opex_injection),
        ("содержание фонда", totals.opex_wellstock),
        ("налог на имущество", totals.property_tax),
        ("событийные затраты", totals.event_costs),
        ("CAPEX ЭЦН", totals.capex_esp),
        ("EBITDA", totals.ebitda),
        ("налог на прибыль", totals.income_tax),
        ("FCF", totals.fcf),
    ):
        lines.append(f"  {caption:24s} {value / RUB_PER_MILLION:14.3f}")
    lines.append("")

    events = analysis.events
    lines.append("СОБЫТИЯ")
    lines.append(
        f"  переводов под закачку {events.conversion_count} на "
        f"{events.conversion_cost_rub / RUB_PER_MILLION:.3f} млн руб"
    )
    lines.append(
        f"  остановок и запусков {events.stop_start_count} на "
        f"{events.stop_start_cost_rub / RUB_PER_MILLION:.3f} млн руб "
        f"(из них вводов {events.commissioning_count})"
    )
    lines.append(
        f"  замен ЭЦН {events.esp_swap_count}: CAPEX "
        f"{events.esp_capex_rub / RUB_PER_MILLION:.3f} + OPEX операции "
        f"{events.esp_swap_opex_rub / RUB_PER_MILLION:.3f} = "
        f"{events.esp_total_rub / RUB_PER_MILLION:.3f} млн руб"
    )
    lines.append(
        f"  первичных оснащений ЭЦН {events.esp_initial_count}, не оплачивается"
    )
    lines.append("")

    lines.append("ПО ГОДАМ, млн руб")
    lines.append(
        f"  {'год':>6} {'выручка':>12} {'OPEX':>12} {'CAPEX':>9} "
        f"{'налог':>10} {'FCF':>12} {'DF':>7} {'ЧДД':>12}"
    )
    for year in analysis.years:
        item = analysis.table.by_year[year]
        structure = cost_structure(item)
        lines.append(
            f"  {year:6d} {item.revenue / RUB_PER_MILLION:12.2f} "
            f"{structure.opex_total / RUB_PER_MILLION:12.2f} "
            f"{item.capex_esp / RUB_PER_MILLION:9.3f} "
            f"{item.income_tax / RUB_PER_MILLION:10.2f} "
            f"{item.fcf / RUB_PER_MILLION:12.2f} "
            f"{item.df:7.4f} {item.discounted_fcf / RUB_PER_MILLION:12.2f}"
        )
    lines.append("")

    ranking = analysis.ranking(TaxBasis.BEFORE_TAX)
    negative = ranking.negative()
    lines.append(f"УБЫТОЧНЫЕ СКВАЖИНЫ ({TaxBasis.BEFORE_TAX.value}): {len(negative)}")
    lines.append(f"  {ranking.caption}")
    for item in ranking.worst(15):
        lines.append(
            f"  {item.well:>8} ЧДД {item.discounted_fcf / RUB_PER_MILLION:10.3f}  "
            f"выручка {item.revenue / RUB_PER_MILLION:10.3f}  "
            f"OPEX {item.opex_total / RUB_PER_MILLION:10.3f}  "
            f"событий {item.event_costs / RUB_PER_MILLION:8.3f}  "
            f"ЭЦН {item.capex_esp / RUB_PER_MILLION:7.3f}"
        )
    lines.append("")
    lines.append("ЛУЧШИЕ СКВАЖИНЫ")
    for item in ranking.best(10):
        lines.append(
            f"  {item.well:>8} ЧДД {item.discounted_fcf / RUB_PER_MILLION:10.3f}"
        )
    lines.append("")
    lines.append(analysis.decomposition.invariants.format())
    return "\n".join(lines)
