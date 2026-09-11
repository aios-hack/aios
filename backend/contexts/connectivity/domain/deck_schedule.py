from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from backend.contexts.schedule.domain.schedule import OperatingStatus, Role


@dataclass(frozen=True, slots=True)
class DeckWellRecord:
    deck_date_index: int
    well: str
    role: Role
    operating_status: OperatingStatus
    setpoint_m3_per_day: float


@dataclass(frozen=True, slots=True)
class DeckSchedule:
    dates: tuple[date, ...]
    wells: tuple[str, ...]
    records: tuple[DeckWellRecord, ...]

    def __post_init__(self) -> None:
        if not self.dates:
            raise ValueError("the deck has no DATES at all")
        if sorted(self.dates) != list(self.dates):
            raise ValueError("the deck DATES are not monotonic")
        if not self.wells:
            raise ValueError("the deck has no WELSPECS")
        declared = set(self.wells)
        unknown = {r.well for r in self.records} - declared
        if unknown:
            raise ValueError(f"wells outside WELSPECS: {sorted(unknown)}")

    def date_index(self, when: date) -> int:
        low, high = 0, len(self.dates)
        while low < high:
            middle = (low + high) // 2
            if self.dates[middle] <= when:
                low = middle + 1
            else:
                high = middle
        if low == 0:
            raise ValueError(
                f"{when} precedes the first deck date {self.dates[0]}: "
                f"no well stock state exists at that date"
            )
        return low - 1

    def records_at(self, deck_date_index: int) -> tuple[DeckWellRecord, ...]:
        return tuple(r for r in self.records if r.deck_date_index == deck_date_index)
