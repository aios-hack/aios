from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Mapping, Sequence

from backend.contexts.reservoir.domain.horizon import HORIZON
from backend.shared.hashing import utf16_code_units

N_CONTROL_DATES = HORIZON.n_intervals + 1
N_INTERVALS = HORIZON.n_intervals
T0 = HORIZON.t0

MAX_LRAT_M3_PER_DAY = 500.0


class Availability(Enum):
    NOT_COMMISSIONED = "NOT_COMMISSIONED"
    AVAILABLE = "AVAILABLE"


class Role(Enum):
    NONE = "NONE"
    PROD = "PROD"
    INJ = "INJ"


class OperatingStatus(Enum):
    OPEN = "OPEN"
    SHUT = "SHUT"


class EventKind(Enum):
    SET_LRAT = "SET_LRAT"
    SET_RATE = "SET_RATE"
    OPEN = "OPEN"
    SHUT = "SHUT"
    CONVERT_INJ = "CONVERT_INJ"


_VALUE_REQUIRED = {EventKind.SET_LRAT, EventKind.SET_RATE}


@dataclass(frozen=True, slots=True)
class WellState:

    availability: Availability
    role: Role
    operating_status: OperatingStatus
    setpoint: float

    def __post_init__(self) -> None:
        if self.availability is Availability.NOT_COMMISSIONED:
            if self.role is not Role.NONE:
                raise ValueError("NOT_COMMISSIONED requires role=NONE")
            if self.operating_status is not OperatingStatus.SHUT:
                raise ValueError(
                    "NOT_COMMISSIONED requires operating_status=SHUT"
                )
            if self.setpoint != 0.0:
                raise ValueError("NOT_COMMISSIONED requires setpoint=0.0")


@dataclass(frozen=True, slots=True)
class FixedDeckEvent:

    control_step: int
    well: str
    operator: str
    raw_args: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ControlEvent:

    control_step: int
    well: str
    kind: EventKind
    value: float | None = None

    def __post_init__(self) -> None:
        if not (0 <= self.control_step <= N_INTERVALS - 1):
            raise ValueError(
                f"control_step={self.control_step} is outside "
                f"0...{N_INTERVALS - 1}: control_step={N_INTERVALS} is "
                f"terminal_state and carries no control events "
                f"(README.md 1.2, 2)"
            )
        needs_value = self.kind in _VALUE_REQUIRED
        if needs_value and self.value is None:
            raise ValueError(f"{self.kind} requires value")
        if not needs_value and self.value is not None:
            raise ValueError(f"{self.kind} does not accept value")
        if self.value is not None and self.value < 0:
            raise ValueError(f"{self.kind}: negative setpoint {self.value}")
        if self.kind is EventKind.SET_LRAT and self.value is not None:
            if self.value > MAX_LRAT_M3_PER_DAY:
                raise ValueError(
                    f"SET_LRAT={self.value} exceeds the Methodology ceiling "
                    f"{MAX_LRAT_M3_PER_DAY} m3/day: the reference NPV "
                    f"calculator fails with an error on such input, and there "
                    f"is only one submission attempt"
                )


@dataclass(frozen=True, slots=True)
class ScheduleMeta:
    model: str = "Model_Z"
    t0: date = T0
    n_control_dates: int = N_CONTROL_DATES
    n_intervals: int = N_INTERVALS
    wells: tuple[str, ...] = field(default_factory=tuple)
    history_prefix_hash: str = ""
    fixed_events_hash: str = ""
    control_events_hash: str = ""
    provenance: str = ""


@dataclass(frozen=True, slots=True)
class Schedule:

    meta: ScheduleMeta
    initial_state: Mapping[str, WellState]
    fixed_deck_events: Sequence[FixedDeckEvent]
    control_events: Sequence[ControlEvent]
