from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aios_backend.core.contracts import Availability, OperatingStatus, Role, WellState

from aios_backend.domain.connectivity.deck import DeckSchedule


@dataclass(frozen=True, slots=True)
class Window:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"пустое окно {self.start}…{self.end}")

    def contains(self, when: date) -> bool:
        return self.start <= when < self.end


@dataclass(frozen=True, slots=True)
class ActiveFund:
    when: date
    deck_date_index: int
    injectors: tuple[str, ...]
    producers: tuple[str, ...]
    commissioned: tuple[str, ...]

    def __post_init__(self) -> None:
        overlap = set(self.injectors) & set(self.producers)
        if overlap:
            raise ValueError(f"скважина в двух ролях сразу: {sorted(overlap)}")
        outside = (set(self.injectors) | set(self.producers)) - set(self.commissioned)
        if outside:
            raise ValueError(f"роль у невведённой скважины: {sorted(outside)}")

    @property
    def plan_width(self) -> int:
        return len(self.injectors)


@dataclass(frozen=True, slots=True)
class FundHistory:
    dates: tuple[date, ...]
    states: tuple[dict[str, WellState], ...]

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.states):
            raise ValueError("длины осей dates и states разошлись")

    def state_at(self, deck_date_index: int) -> dict[str, WellState]:
        if not (0 <= deck_date_index < len(self.states)):
            raise ValueError(
                f"deck_date_index={deck_date_index} вне 0…{len(self.states) - 1}"
            )
        return self.states[deck_date_index]


def _normalized(
    role: Role, operating_status: OperatingStatus, setpoint: float
) -> WellState:
    return WellState(
        availability=Availability.AVAILABLE,
        role=role,
        operating_status=operating_status,
        setpoint=setpoint,
    )


_NOT_COMMISSIONED = WellState(
    availability=Availability.NOT_COMMISSIONED,
    role=Role.NONE,
    operating_status=OperatingStatus.SHUT,
    setpoint=0.0,
)


def build_fund_history(deck: DeckSchedule) -> FundHistory:
    by_index: dict[int, list] = {}
    for record in deck.records:
        by_index.setdefault(record.deck_date_index, []).append(record)
    running: dict[str, WellState] = {well: _NOT_COMMISSIONED for well in deck.wells}
    states: list[dict[str, WellState]] = []
    for deck_date_index in range(len(deck.dates)):
        for record in by_index.get(deck_date_index, ()):
            running[record.well] = _normalized(
                record.role,
                record.operating_status,
                record.setpoint_m3_per_day,
            )
        states.append(dict(running))
    return FundHistory(dates=deck.dates, states=tuple(states))


def _fund_from_state(
    when: date, deck_date_index: int, state: dict[str, WellState]
) -> ActiveFund:
    injectors: list[str] = []
    producers: list[str] = []
    commissioned: list[str] = []
    for well, well_state in state.items():
        if well_state.availability is not Availability.AVAILABLE:
            continue
        commissioned.append(well)
        if well_state.operating_status is not OperatingStatus.OPEN:
            continue
        if well_state.role is Role.INJ:
            injectors.append(well)
        elif well_state.role is Role.PROD:
            producers.append(well)
    return ActiveFund(
        when=when,
        deck_date_index=deck_date_index,
        injectors=tuple(sorted(injectors)),
        producers=tuple(sorted(producers)),
        commissioned=tuple(sorted(commissioned)),
    )


def active_fund_at(
    deck: DeckSchedule, when: date, history: FundHistory | None = None
) -> ActiveFund:
    resolved = history if history is not None else build_fund_history(deck)
    deck_date_index = deck.date_index(when)
    return _fund_from_state(when, deck_date_index, resolved.state_at(deck_date_index))


def active_fund_in_window(
    deck: DeckSchedule, window: Window, history: FundHistory | None = None
) -> ActiveFund:
    resolved = history if history is not None else build_fund_history(deck)
    fund = active_fund_at(deck, window.start, resolved)
    entered = _wells_entering_inside(deck, window, resolved)
    injectors = tuple(w for w in fund.injectors if w not in entered)
    producers = tuple(w for w in fund.producers if w not in entered)
    return ActiveFund(
        when=window.start,
        deck_date_index=fund.deck_date_index,
        injectors=injectors,
        producers=producers,
        commissioned=fund.commissioned,
    )


def _wells_entering_inside(
    deck: DeckSchedule, window: Window, history: FundHistory
) -> set[str]:
    start_index = deck.date_index(window.start)
    entered: set[str] = set()
    previous = history.state_at(start_index)
    for deck_date_index in range(start_index + 1, len(deck.dates)):
        if not window.contains(deck.dates[deck_date_index]):
            break
        current = history.state_at(deck_date_index)
        for well, state in current.items():
            if state.role is not previous[well].role:
                entered.add(well)
        previous = current
    return entered


def slice_windows(
    deck: DeckSchedule,
    boundaries: tuple[date, ...],
    history: FundHistory | None = None,
) -> tuple[tuple[Window, ActiveFund], ...]:
    if len(boundaries) < 2:
        raise ValueError("для нарезки окон нужны минимум две границы")
    if sorted(boundaries) != list(boundaries) or len(set(boundaries)) != len(boundaries):
        raise ValueError("границы окон обязаны строго возрастать")
    resolved = history if history is not None else build_fund_history(deck)
    sliced: list[tuple[Window, ActiveFund]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        window = Window(start=start, end=end)
        sliced.append((window, active_fund_in_window(deck, window, resolved)))
    return tuple(sliced)
