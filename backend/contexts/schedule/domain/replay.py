from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from backend.core.contracts import (
    Availability,
    OperatingStatus,
    Role,
    T0,
    WellState,
)

from .lossless import LosslessBlock, ParsedSchedule, block_records, line_keyword

_FUND_KEYWORDS = ("WCONPROD", "WCONINJE")


class ReplayError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Conversion:
    well: str
    event_date: date


@dataclass(frozen=True, slots=True)
class ReplayResult:
    state: dict[str, WellState]
    conversions: tuple[Conversion, ...]
    commissioned: tuple[str, ...]
    not_commissioned: tuple[str, ...]
    applied_blocks: int


@dataclass(slots=True)
class _MutableWell:
    availability: Availability = Availability.NOT_COMMISSIONED
    role: Role = Role.NONE
    operating_status: OperatingStatus = OperatingStatus.SHUT
    setpoint: float = 0.0
    commissioned_at: date | None = None

    def freeze(self) -> WellState:
        if self.availability is Availability.NOT_COMMISSIONED:
            return WellState(
                availability=Availability.NOT_COMMISSIONED,
                role=Role.NONE,
                operating_status=OperatingStatus.SHUT,
                setpoint=0.0,
            )
        return WellState(
            availability=Availability.AVAILABLE,
            role=self.role,
            operating_status=self.operating_status,
            setpoint=self.setpoint,
        )


@dataclass(slots=True)
class _Fund:
    wells: dict[str, _MutableWell] = field(default_factory=dict)
    conversions: list[Conversion] = field(default_factory=list)

    def touch(self, well: str) -> _MutableWell:
        state = self.wells.get(well)
        if state is None:
            state = _MutableWell()
            self.wells[well] = state
        return state


def _status(token: str, keyword: str, well: str) -> OperatingStatus:
    try:
        return OperatingStatus[token]
    except KeyError as error:
        raise ReplayError(
            f"{keyword} {well!r}: неизвестный статус скважины {token!r}"
        ) from error


def _float(token: str, keyword: str, well: str) -> float:
    try:
        return float(token)
    except ValueError as error:
        raise ReplayError(
            f"{keyword} {well!r}: уставка не является числом: {token!r}"
        ) from error


def _prod_fields(record: tuple[str, ...]) -> tuple[OperatingStatus, float]:
    well = record[0]
    if len(record) < 7 or record[2] != "LRAT":
        raise ReplayError(f"WCONPROD {well!r}: ожидается режим LRAT, получено {record!r}")
    return _status(record[1], "WCONPROD", well), _float(record[6], "WCONPROD", well)


def _inj_fields(record: tuple[str, ...]) -> tuple[OperatingStatus, float]:
    well = record[0]
    if len(record) < 5 or record[1] != "WATER" or record[3] != "RATE":
        raise ReplayError(
            f"WCONINJE {well!r}: ожидаются фаза WATER и режим RATE, получено {record!r}"
        )
    return _status(record[2], "WCONINJE", well), _float(record[4], "WCONINJE", well)


def _records(block: LosslessBlock) -> list[tuple[str, ...]]:
    lines = block.raw.splitlines(keepends=True)
    return block_records(lines, line_keyword(lines[0]))


def _apply_record(
    fund: _Fund, keyword: str, record: tuple[str, ...], event_date: date
) -> None:
    well = record[0]
    state = fund.touch(well)
    if keyword == "WCONPROD":
        status, setpoint = _prod_fields(record)
        new_role = Role.PROD
    else:
        status, setpoint = _inj_fields(record)
        new_role = Role.INJ

    if state.role is Role.PROD and new_role is Role.INJ:
        fund.conversions.append(Conversion(well=well, event_date=event_date))

    if state.availability is Availability.NOT_COMMISSIONED:
        state.availability = Availability.AVAILABLE
        state.commissioned_at = event_date

    state.role = new_role
    state.operating_status = status
    state.setpoint = setpoint


def history_blocks(parsed: ParsedSchedule, t0: date = T0) -> tuple[LosslessBlock, ...]:
    return tuple(
        block
        for block in parsed.blocks
        if block.keyword in _FUND_KEYWORDS
        and block.event_date is not None
        and block.event_date < t0
    )


def replay(
    parsed: ParsedSchedule, wells: tuple[str, ...], t0: date = T0
) -> ReplayResult:
    fund = _Fund()
    blocks = history_blocks(parsed, t0)
    for block in blocks:
        for record in _records(block):
            if block.event_date is None:
                raise ReplayError(f"{block.keyword}: блок истории без даты")
            _apply_record(fund, block.keyword, record, block.event_date)

    axis = set(wells)
    unknown = sorted(set(fund.wells) - axis)
    if unknown:
        raise ReplayError(f"история содержит скважины вне оси WELSPECS: {unknown}")

    state: dict[str, WellState] = {}
    commissioned: list[str] = []
    not_commissioned: list[str] = []
    for well in wells:
        mutable = fund.wells.get(well)
        frozen = _MutableWell().freeze() if mutable is None else mutable.freeze()
        state[well] = frozen
        if frozen.availability is Availability.AVAILABLE:
            commissioned.append(well)
        else:
            not_commissioned.append(well)

    return ReplayResult(
        state=state,
        conversions=tuple(fund.conversions),
        commissioned=tuple(commissioned),
        not_commissioned=tuple(not_commissioned),
        applied_blocks=len(blocks),
    )


def replay_initial_state(
    parsed: ParsedSchedule, wells: tuple[str, ...], t0: date = T0
) -> dict[str, WellState]:
    return replay(parsed, wells, t0).state
