from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from contracts import ChargeInitialEsp, EspCatalogEntry, NormativeSet, StateAtDate

DOWNSIZE_THRESHOLD_M3_PER_DAY: float = 100.0

ESP_CATALOG_2007: tuple[EspCatalogEntry, ...] = (
    EspCatalogEntry(nominal=15.0, interval_low=0.0, interval_high=20.0, cost_rub=550_000.0),
    EspCatalogEntry(nominal=20.0, interval_low=15.0, interval_high=30.0, cost_rub=650_000.0),
    EspCatalogEntry(nominal=30.0, interval_low=20.0, interval_high=50.0, cost_rub=750_000.0),
    EspCatalogEntry(nominal=50.0, interval_low=30.0, interval_high=80.0, cost_rub=903_970.0),
    EspCatalogEntry(nominal=80.0, interval_low=50.0, interval_high=100.0, cost_rub=1_850_000.0),
    EspCatalogEntry(nominal=100.0, interval_low=80.0, interval_high=125.0, cost_rub=2_300_000.0),
    EspCatalogEntry(nominal=125.0, interval_low=100.0, interval_high=160.0, cost_rub=2_750_000.0),
    EspCatalogEntry(nominal=160.0, interval_low=125.0, interval_high=210.0, cost_rub=3_350_000.0),
    EspCatalogEntry(nominal=210.0, interval_low=160.0, interval_high=250.0, cost_rub=4_100_000.0),
    EspCatalogEntry(nominal=250.0, interval_low=210.0, interval_high=320.0, cost_rub=4_750_000.0),
    EspCatalogEntry(nominal=320.0, interval_low=250.0, interval_high=400.0, cost_rub=6_000_000.0),
    EspCatalogEntry(nominal=400.0, interval_low=320.0, interval_high=500.0, cost_rub=8_050_000.0),
)


class EspEventKind(Enum):
    INITIAL = "INITIAL"
    UPSIZE = "UPSIZE"
    DOWNSIZE = "DOWNSIZE"


@dataclass(frozen=True, slots=True)
class EspEvent:
    deck_step: int
    well: str
    kind: EspEventKind
    previous_nominal: float | None
    new_nominal: float
    capex_rub: float
    opex_rub: float


@dataclass(frozen=True, slots=True)
class WellEspTrack:
    well: str
    nominal_by_deck_step: tuple[float | None, ...]
    events: tuple[EspEvent, ...]
    final_nominal: float | None

    @property
    def total_capex_rub(self) -> float:
        return sum(event.capex_rub for event in self.events)

    @property
    def total_opex_rub(self) -> float:
        return sum(event.opex_rub for event in self.events)


def pick_initial_esp(
    rate: float, catalog: Sequence[EspCatalogEntry]
) -> EspCatalogEntry:
    candidates = [
        entry
        for entry in catalog
        if entry.interval_low <= rate <= entry.interval_high
    ]
    if candidates:
        return min(candidates, key=lambda entry: entry.nominal)
    if rate > catalog[-1].interval_high:
        return catalog[-1]
    return catalog[0]


def pick_upsize_esp(
    rate: float, current: EspCatalogEntry, catalog: Sequence[EspCatalogEntry]
) -> EspCatalogEntry:
    candidates = [
        entry
        for entry in catalog
        if entry.nominal > current.nominal
        and entry.interval_low <= rate <= entry.interval_high
    ]
    if candidates:
        return min(candidates, key=lambda entry: entry.nominal)
    higher = [entry for entry in catalog if entry.nominal > current.nominal]
    return higher[-1] if higher else current


def pick_downsize_esp(
    rate: float, current: EspCatalogEntry, catalog: Sequence[EspCatalogEntry]
) -> EspCatalogEntry:
    candidates = [
        entry
        for entry in catalog
        if entry.nominal < current.nominal
        and entry.interval_low <= rate <= entry.interval_high
    ]
    if candidates:
        return max(candidates, key=lambda entry: entry.nominal)
    lower = [entry for entry in catalog if entry.nominal < current.nominal]
    return lower[0] if lower else current


class EspStateMachine:
    def __init__(
        self, normatives: NormativeSet, charge_initial_esp: ChargeInitialEsp
    ) -> None:
        if not normatives.esp_catalog:
            raise ValueError("esp_catalog пуст")
        self._catalog: tuple[EspCatalogEntry, ...] = tuple(
            sorted(normatives.esp_catalog, key=lambda entry: entry.nominal)
        )
        self._swap_opex_rub: float = normatives.esp_swap_opex_rub
        self._charge_initial: bool = (
            charge_initial_esp is ChargeInitialEsp.CHARGED_AT_FIRST_STEP
        )

    def track_well(
        self,
        well: str,
        states_by_deck_step: Sequence[StateAtDate],
        n_intervals: int,
        excluded_deck_steps: frozenset[int],
    ) -> WellEspTrack:
        n_deck_dates = len(states_by_deck_step)
        if n_intervals <= 0:
            raise ValueError(f"скважина {well}: n_intervals={n_intervals}")
        if n_deck_dates <= n_intervals:
            raise ValueError(
                f"скважина {well}: дат дека {n_deck_dates} — не больше числа "
                f"интервалов {n_intervals}, истории нет"
            )
        for deck_step, state in enumerate(states_by_deck_step):
            if state.well != well:
                raise ValueError(
                    f"скважина {well}: StateAtDate на позиции {deck_step} "
                    f"принадлежит {state.well}"
                )
            if state.deck_date_index != deck_step:
                raise ValueError(
                    f"скважина {well}: deck_date_index={state.deck_date_index} "
                    f"на позиции {deck_step}, ряд не плотный — автомат ЭЦН "
                    f"требует полную траекторию"
                )
        for deck_step in excluded_deck_steps:
            if not (0 <= deck_step < n_deck_dates):
                raise ValueError(
                    f"скважина {well}: исключённый шаг {deck_step} вне дека"
                )

        charge_from_deck_step = n_deck_dates - n_intervals
        current: EspCatalogEntry | None = None
        nominal_track: list[float | None] = []
        events: list[EspEvent] = []

        for deck_step, state in enumerate(states_by_deck_step):
            if deck_step in excluded_deck_steps:
                nominal_track.append(current.nominal if current else None)
                continue
            rate = max(0.0, state.liquid_rate)
            pending: tuple[EspEventKind, float | None, EspCatalogEntry] | None = None
            if rate > 0:
                if current is None:
                    current = pick_initial_esp(rate, self._catalog)
                    if self._charge_initial and deck_step >= charge_from_deck_step:
                        pending = (EspEventKind.INITIAL, None, current)
                elif rate > current.interval_high:
                    candidate = pick_upsize_esp(rate, current, self._catalog)
                    if candidate.nominal != current.nominal:
                        pending = (EspEventKind.UPSIZE, current.nominal, candidate)
                        current = candidate
                elif current.interval_low - rate > DOWNSIZE_THRESHOLD_M3_PER_DAY:
                    candidate = pick_downsize_esp(rate, current, self._catalog)
                    if candidate.nominal != current.nominal:
                        pending = (EspEventKind.DOWNSIZE, current.nominal, candidate)
                        current = candidate
            if (
                self._charge_initial
                and deck_step == charge_from_deck_step
                and rate > 0
                and current is not None
                and pending is None
            ):
                pending = (EspEventKind.INITIAL, None, current)
            if pending is not None and deck_step >= charge_from_deck_step:
                kind, previous_nominal, new_entry = pending
                events.append(
                    EspEvent(
                        deck_step=deck_step,
                        well=well,
                        kind=kind,
                        previous_nominal=previous_nominal,
                        new_nominal=new_entry.nominal,
                        capex_rub=new_entry.cost_rub,
                        opex_rub=self._swap_opex_rub,
                    )
                )
            nominal_track.append(current.nominal if current else None)

        return WellEspTrack(
            well=well,
            nominal_by_deck_step=tuple(nominal_track),
            events=tuple(events),
            final_nominal=current.nominal if current else None,
        )
