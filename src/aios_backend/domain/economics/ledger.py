from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from aios_backend.core.contracts import (
    IntervalResponse,
    NormativeSet,
    StateAtDate,
    is_excluded_by_negative_rule,
)

from .fund import ACTIVE_FUND_STATES, FundState, FundTransition, track_well


class LedgerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CumulativeSeries:
    well: str
    oil_mass_t: tuple[float, ...]
    liquid_volume_m3: tuple[float, ...]
    injection_volume_m3: tuple[float, ...]

    def __post_init__(self) -> None:
        lengths = {
            len(self.oil_mass_t),
            len(self.liquid_volume_m3),
            len(self.injection_volume_m3),
        }
        if len(lengths) != 1:
            raise LedgerError(
                f"скважина {self.well}: накопленные ряды разной длины {sorted(lengths)}"
            )
        if lengths == {0}:
            raise LedgerError(f"скважина {self.well}: пустой накопленный ряд")


@dataclass(frozen=True, slots=True)
class LedgerRow:
    control_step: int
    well: str
    year: int
    oil_mass_t: float
    liquid_volume_m3: float
    injection_volume_m3: float
    fund_state: FundState
    is_active: bool
    event_cost_rub: float


@dataclass(frozen=True, slots=True)
class WellLedger:
    well: str
    rows: tuple[LedgerRow, ...]
    excluded_control_steps: frozenset[int]
    transitions: tuple[FundTransition, ...]

    @property
    def rows_by_control_step(self) -> dict[int, LedgerRow]:
        return {row.control_step: row for row in self.rows}

    @property
    def total_oil_mass_t(self) -> float:
        return sum(row.oil_mass_t for row in self.rows)

    @property
    def total_liquid_volume_m3(self) -> float:
        return sum(row.liquid_volume_m3 for row in self.rows)

    @property
    def total_injection_volume_m3(self) -> float:
        return sum(row.injection_volume_m3 for row in self.rows)


@dataclass(frozen=True, slots=True)
class PeriodAggregate:
    oil_mass_t: float
    liquid_volume_m3: float
    injection_volume_m3: float
    active_well_count: int
    event_cost_rub: float


@dataclass(frozen=True, slots=True)
class ProductionLedger:
    wells: tuple[str, ...]
    n_intervals: int
    interval_years: tuple[int, ...]
    by_well: Mapping[str, WellLedger]

    @property
    def rows(self) -> tuple[LedgerRow, ...]:
        return tuple(
            row
            for well in self.wells
            for row in self.by_well[well].rows
        )

    def by_control_step(self) -> dict[int, PeriodAggregate]:
        return _aggregate(self.rows, lambda row: row.control_step)

    def by_year(self) -> dict[int, PeriodAggregate]:
        return _aggregate(self.rows, lambda row: row.year)

    def field_totals(self) -> PeriodAggregate:
        return _combine(self.rows)


def _aggregate(rows: Sequence[LedgerRow], key) -> dict[int, PeriodAggregate]:
    buckets: dict[int, list[LedgerRow]] = {}
    for row in rows:
        buckets.setdefault(key(row), []).append(row)
    return {bucket: _combine(items) for bucket, items in sorted(buckets.items())}


def _combine(rows: Sequence[LedgerRow]) -> PeriodAggregate:
    return PeriodAggregate(
        oil_mass_t=sum(row.oil_mass_t for row in rows),
        liquid_volume_m3=sum(row.liquid_volume_m3 for row in rows),
        injection_volume_m3=sum(row.injection_volume_m3 for row in rows),
        active_well_count=sum(1 for row in rows if row.is_active),
        event_cost_rub=sum(row.event_cost_rub for row in rows),
    )


def raw_diff(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(values[i + 1] - values[i] for i in range(len(values) - 1))


def interval_responses_from_cumulative(
    series: CumulativeSeries, n_intervals: int
) -> tuple[IntervalResponse, ...]:
    n_deck_dates = len(series.oil_mass_t)
    if n_intervals <= 0:
        raise LedgerError(f"скважина {series.well}: n_intervals={n_intervals}")
    if n_deck_dates <= n_intervals:
        raise LedgerError(
            f"скважина {series.well}: дат дека {n_deck_dates} — не больше числа "
            f"интервалов {n_intervals}, истории нет"
        )
    oil = raw_diff(series.oil_mass_t)
    liquid = raw_diff(series.liquid_volume_m3)
    injection = raw_diff(series.injection_volume_m3)
    first_interval_start = n_deck_dates - 1 - n_intervals
    return tuple(
        IntervalResponse(
            control_step=control_step,
            well=series.well,
            oil_mass_delta=oil[first_interval_start + control_step],
            liquid_volume_delta=liquid[first_interval_start + control_step],
            injection_volume_delta=injection[first_interval_start + control_step],
        )
        for control_step in range(n_intervals)
    )


def responses_by_well_from_cumulative(
    series_by_well: Sequence[CumulativeSeries], n_intervals: int
) -> dict[str, tuple[IntervalResponse, ...]]:
    responses: dict[str, tuple[IntervalResponse, ...]] = {}
    for series in series_by_well:
        if series.well in responses:
            raise LedgerError(f"скважина {series.well}: накопленный ряд задан дважды")
        responses[series.well] = interval_responses_from_cumulative(series, n_intervals)
    return responses


def interval_years(interval_start_dates: Sequence[date]) -> tuple[int, ...]:
    if not interval_start_dates:
        raise LedgerError("пустой ряд дат интервалов")
    return tuple(moment.year for moment in interval_start_dates)


def build_well_ledger(
    well: str,
    states_by_deck_step: Sequence[StateAtDate],
    responses_by_control_step: Sequence[IntervalResponse],
    years_by_control_step: Sequence[int],
    normatives: NormativeSet,
) -> WellLedger:
    n_intervals = len(responses_by_control_step)
    if len(years_by_control_step) != n_intervals:
        raise LedgerError(
            f"скважина {well}: {len(years_by_control_step)} годов на "
            f"{n_intervals} интервалов"
        )
    track = track_well(well, states_by_deck_step, responses_by_control_step, normatives)
    rows: list[LedgerRow] = []
    excluded: list[int] = []
    for control_step, response in enumerate(responses_by_control_step):
        if is_excluded_by_negative_rule(response):
            excluded.append(control_step)
            continue
        state = track.state_by_control_step[control_step]
        rows.append(
            LedgerRow(
                control_step=control_step,
                well=well,
                year=years_by_control_step[control_step],
                oil_mass_t=response.oil_mass_delta,
                liquid_volume_m3=response.liquid_volume_delta,
                injection_volume_m3=response.injection_volume_delta,
                fund_state=state,
                is_active=state in ACTIVE_FUND_STATES,
                event_cost_rub=track.event_costs_by_control_step[control_step],
            )
        )
    return WellLedger(
        well=well,
        rows=tuple(rows),
        excluded_control_steps=frozenset(excluded),
        transitions=track.transitions,
    )


def build_production_ledger(
    states_by_well: Mapping[str, Sequence[StateAtDate]],
    responses_by_well: Mapping[str, Sequence[IntervalResponse]],
    interval_start_dates: Sequence[date],
    normatives: NormativeSet,
) -> ProductionLedger:
    if not states_by_well:
        raise LedgerError("пустая ось скважин")
    if set(states_by_well) != set(responses_by_well):
        missing = sorted(set(states_by_well) ^ set(responses_by_well))
        raise LedgerError(f"оси скважин не совпадают: {missing}")
    years = interval_years(interval_start_dates)
    n_intervals = len(years)
    wells = tuple(sorted(states_by_well))
    by_well: dict[str, WellLedger] = {}
    for well in wells:
        responses = responses_by_well[well]
        if len(responses) != n_intervals:
            raise LedgerError(
                f"скважина {well}: {len(responses)} интервалов при {n_intervals} датах"
            )
        by_well[well] = build_well_ledger(
            well,
            states_by_well[well],
            responses,
            years,
            normatives,
        )
    return ProductionLedger(
        wells=wells,
        n_intervals=n_intervals,
        interval_years=years,
        by_well=by_well,
    )
