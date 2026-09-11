from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from backend.contexts.constraints.domain.config import NormativeSet, Policies
from backend.contexts.economics.domain.economics import NpvTable
from backend.contexts.economics.domain.errors import EconomicsError
from backend.contexts.economics.domain.ledger import (
    ProductionLedger,
    build_production_ledger,
)
from backend.contexts.economics.domain.npv.cell_flows import build_cell_flows
from backend.contexts.economics.domain.npv.table import (
    compute_npv_table,
    npv_table_from_flows,
)
from backend.contexts.economics.domain.npv.terms import (
    BalanceSheetInputs,
    CellFlows,
    DISCOUNT_BASE_YEAR,
)
from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate
from backend.contexts.schedule.domain.schedule import Schedule


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
                f"the schedule declares {schedule.meta.n_intervals} intervals, "
                f"interval dates {len(interval_start_dates)}"
            )
        wells = set(states_by_well)
        if wells != set(responses_by_well):
            raise EconomicsError(
                f"response well axes do not match: "
                f"{sorted(wells ^ set(responses_by_well))}"
            )
        if schedule.initial_state and set(schedule.initial_state) != wells:
            raise EconomicsError(
                f"the schedule well axis does not match the response axis: "
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
