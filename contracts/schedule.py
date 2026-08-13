"""Schedule — расписание управления. README.md §2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Mapping, Sequence

N_CONTROL_DATES = 225
N_INTERVALS = 224
T0 = date(2007, 1, 1)


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
    """Состояние скважины. README.md §2 «Состояние скважины»."""

    availability: Availability
    role: Role
    operating_status: OperatingStatus
    setpoint: float  # м³/сут

    def __post_init__(self) -> None:
        if self.availability is Availability.NOT_COMMISSIONED:
            # Нормализация фиксирована (аудит 14.08, README.md §2): без неё
            # два корректных сериализатора дают разные байты для одной и той
            # же невведённой скважины, и canonical_schedule_hash перестаёт
            # быть каноническим.
            if self.role is not Role.NONE:
                raise ValueError("NOT_COMMISSIONED требует role=NONE")
            if self.operating_status is not OperatingStatus.SHUT:
                raise ValueError("NOT_COMMISSIONED требует operating_status=SHUT")
            if self.setpoint != 0.0:
                raise ValueError("NOT_COMMISSIONED требует setpoint=0.0")


@dataclass(frozen=True, slots=True)
class FixedDeckEvent:
    """Неуправляемый оператор дека внутри горизонта — перфорации, WPIMULT и т.п.

    Не решение агента: переносится в эмитированный файл как есть (README.md §2).
    """

    control_step: int  # 0…224 — фиксированные события деком не ограничены
    well: str
    operator: str  # "COMPDATMD", "WPIMULT", ...
    raw_args: tuple[str, ...]  # аргументы оператора как в исходном деке


@dataclass(frozen=True, slots=True)
class ControlEvent:
    """Управляющее решение. README.md §2 «Управляющее событие»."""

    control_step: int  # 0…223 — 224 это terminal_state, решений не несёт
    well: str
    kind: EventKind
    value: float | None = None  # м³/сут

    def __post_init__(self) -> None:
        if not (0 <= self.control_step <= N_INTERVALS - 1):
            raise ValueError(
                f"control_step={self.control_step} вне 0…{N_INTERVALS - 1}: "
                f"control_step={N_INTERVALS} — terminal_state, управляющих "
                f"событий не несёт (README.md §1.2, §2)"
            )
        needs_value = self.kind in _VALUE_REQUIRED
        if needs_value and self.value is None:
            raise ValueError(f"{self.kind} требует value")
        if not needs_value and self.value is not None:
            raise ValueError(f"{self.kind} не принимает value")


@dataclass(frozen=True, slots=True)
class ScheduleMeta:
    model: str = "Model_Z"
    t0: date = T0
    n_control_dates: int = N_CONTROL_DATES
    n_intervals: int = N_INTERVALS
    wells: tuple[str, ...] = field(default_factory=tuple)  # лексикографический порядок
    history_prefix_hash: str = ""
    fixed_events_hash: str = ""
    control_events_hash: str = ""
    provenance: str = ""


@dataclass(frozen=True, slots=True)
class Schedule:
    """Каноническое расписание, оба слоя. README.md §2."""

    meta: ScheduleMeta
    initial_state: Mapping[str, WellState]
    fixed_deck_events: Sequence[FixedDeckEvent]
    control_events: Sequence[ControlEvent]
