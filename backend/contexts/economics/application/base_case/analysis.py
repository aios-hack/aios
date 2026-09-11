from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from backend.contexts.constraints.domain.config import NormativeSet, Policies
from backend.contexts.economics.application.base_case.totals import (
    CostStructure,
    EventTally,
    RUB_PER_MILLION,
    VolumeTotals,
    cost_structure,
    field_totals,
    tally_events,
    volume_totals,
)
from backend.contexts.economics.application.base_case.artifacts import (
    interval_start_dates,
    responses_by_well_from_artifact,
    states_by_well_from_artifact,
)
from backend.contexts.economics.domain.decomposition import (
    NpvDecomposition,
    TaxBasis,
    WellRanking,
    decompose,
)
from backend.contexts.economics.domain.economics import LineItems, NpvTable
from backend.contexts.economics.domain.errors import BaseCaseError
from backend.contexts.economics.domain.fund import FundState
from backend.contexts.economics.domain.ledger import (
    ProductionLedger,
    build_production_ledger,
)
from backend.contexts.economics.domain.npv import (
    BalanceSheetInputs,
    CellFlows,
    Economics,
)
from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate
from backend.contexts.runs.domain.run_result import ResponseArtifact


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
            f"response well axes do not match: "
            f"{sorted(set(states_by_well) ^ set(responses_by_well))}"
        )
    if not states_by_well:
        raise BaseCaseError("response contains no wells")

    n_deck_dates_by_well = {len(states) for states in states_by_well.values()}
    if len(n_deck_dates_by_well) != 1:
        raise BaseCaseError(
            f"wells carry differing deck date counts: {sorted(n_deck_dates_by_well)}"
        )
    n_intervals_by_well = {len(items) for items in responses_by_well.values()}
    if len(n_intervals_by_well) != 1:
        raise BaseCaseError(
            f"wells carry differing interval counts: {sorted(n_intervals_by_well)}"
        )
    n_deck_dates = n_deck_dates_by_well.pop()
    n_intervals = n_intervals_by_well.pop()
    if len(deck_dates) != n_deck_dates:
        raise BaseCaseError(
            f"deck dates {len(deck_dates)}, response is laid out over {n_deck_dates}"
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


def format_report(analysis: BaseCaseAnalysis) -> str:
    lines: list[str] = []
    lines.append("ECONOMIC BREAKDOWN OF THE BASE CASE")
    lines.append(f"run {analysis.source_run_id}, response {analysis.response_hash[:16]}")
    lines.append(
        f"wells {analysis.n_wells}, deck dates {analysis.n_deck_dates}, "
        f"intervals {analysis.n_intervals}"
    )
    lines.append(
        f"rows excluded by the negative-increment rule: "
        f"{analysis.excluded_row_count}, dates {[str(d) for d in analysis.excluded_dates]}"
    )
    lines.append("")
    lines.append(
        f"NPV per the Methodology: {analysis.npv_methodology / RUB_PER_MILLION:.3f} mln RUB"
    )
    lines.append("")

    volumes = analysis.volumes
    lines.append(
        f"oil {volumes.oil_mass_t / 1000.0:.1f} kt, "
        f"liquid {volumes.liquid_volume_m3 / 1000.0:.1f} k m3, "
        f"injection {volumes.injection_volume_m3 / 1000.0:.1f} k m3"
    )
    lines.append("")

    totals = analysis.totals
    lines.append("STRUCTURE, mln RUB over the horizon (undiscounted)")
    for caption, value in (
        ("revenue", totals.revenue),
        ("deductions", totals.deductions),
        ("OPEX oil", totals.opex_oil),
        ("OPEX liquid", totals.opex_liquid),
        ("OPEX injection", totals.opex_injection),
        ("well stock upkeep", totals.opex_wellstock),
        ("property tax", totals.property_tax),
        ("event costs", totals.event_costs),
        ("CAPEX ESP", totals.capex_esp),
        ("EBITDA", totals.ebitda),
        ("income tax", totals.income_tax),
        ("FCF", totals.fcf),
    ):
        lines.append(f"  {caption:24s} {value / RUB_PER_MILLION:14.3f}")
    lines.append("")

    events = analysis.events
    lines.append("EVENTS")
    lines.append(
        f"  conversions to injection {events.conversion_count} for "
        f"{events.conversion_cost_rub / RUB_PER_MILLION:.3f} mln RUB"
    )
    lines.append(
        f"  stops and starts {events.stop_start_count} for "
        f"{events.stop_start_cost_rub / RUB_PER_MILLION:.3f} mln RUB "
        f"(of which commissionings {events.commissioning_count})"
    )
    lines.append(
        f"  ESP swaps {events.esp_swap_count}: CAPEX "
        f"{events.esp_capex_rub / RUB_PER_MILLION:.3f} + OPEX of the operation "
        f"{events.esp_swap_opex_rub / RUB_PER_MILLION:.3f} = "
        f"{events.esp_total_rub / RUB_PER_MILLION:.3f} mln RUB"
    )
    lines.append(
        f"  initial ESP installations {events.esp_initial_count}, not charged"
    )
    lines.append("")

    lines.append("BY YEAR, mln RUB")
    lines.append(
        f"  {'year':>6} {'revenue':>12} {'OPEX':>12} {'CAPEX':>9} "
        f"{'tax':>10} {'FCF':>12} {'DF':>7} {'NPV':>12}"
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
    lines.append(f"LOSS-MAKING WELLS ({TaxBasis.BEFORE_TAX.value}): {len(negative)}")
    lines.append(f"  {ranking.caption}")
    for item in ranking.worst(15):
        lines.append(
            f"  {item.well:>8} NPV {item.discounted_fcf / RUB_PER_MILLION:10.3f}  "
            f"revenue {item.revenue / RUB_PER_MILLION:10.3f}  "
            f"OPEX {item.opex_total / RUB_PER_MILLION:10.3f}  "
            f"events {item.event_costs / RUB_PER_MILLION:8.3f}  "
            f"ESP {item.capex_esp / RUB_PER_MILLION:7.3f}"
        )
    lines.append("")
    lines.append("BEST WELLS")
    for item in ranking.best(10):
        lines.append(
            f"  {item.well:>8} NPV {item.discounted_fcf / RUB_PER_MILLION:10.3f}"
        )
    lines.append("")
    lines.append(analysis.decomposition.invariants.format())
    return "\n".join(lines)
