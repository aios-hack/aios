from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from contracts import (
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    T0,
    WellState,
    canonical_bytes,
    canonical_schedule_hash,
)

from .lossless import (
    ParsedSchedule,
    ScheduleParseError,
    block_records,
    line_keyword,
    parse_schedule,
)

_WELSPECS_RE = re.compile(rb"^WELSPECS\b(.*?)^/\s*$", re.MULTILINE | re.DOTALL)
_WELSPECS_WELL_RE = re.compile(rb"^\s*'([^']+)'", re.MULTILINE)

_KIND_RANK = {
    EventKind.CONVERT_INJ: 0,
    EventKind.SET_LRAT: 1,
    EventKind.SET_RATE: 1,
    EventKind.OPEN: 2,
    EventKind.SHUT: 2,
}


class ScheduleBuildError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ControlEventConflict:
    control_step: int
    well: str
    kind: EventKind
    values: tuple[float | None, ...]


def _well_sort_key(well: str) -> tuple[int, int, str]:
    return (0, int(well), well) if well.isdigit() else (1, 0, well)


def deck_well_axis(raw: bytes) -> tuple[str, ...]:
    match = _WELSPECS_RE.search(raw)
    if match is None:
        raise ScheduleBuildError("в деке нет блока WELSPECS: ось скважин неоткуда взять")
    wells = [well.decode("ascii") for well in _WELSPECS_WELL_RE.findall(match.group(1))]
    if not wells:
        raise ScheduleBuildError("WELSPECS не содержит ни одной скважины")
    unique = sorted(set(wells), key=_well_sort_key)
    if len(unique) != len(wells):
        raise ScheduleBuildError("WELSPECS содержит повторяющиеся скважины")
    return tuple(unique)


def detect_control_conflicts(
    events: tuple[ControlEvent, ...] | list[ControlEvent],
) -> tuple[ControlEventConflict, ...]:
    seen: dict[tuple[int, str, EventKind], list[float | None]] = {}
    for event in events:
        key = (event.control_step, event.well, event.kind)
        values = seen.setdefault(key, [])
        if event.value not in values:
            values.append(event.value)
    conflicts = [
        ControlEventConflict(control_step=step, well=well, kind=kind, values=tuple(values))
        for (step, well, kind), values in seen.items()
        if len(values) > 1
    ]
    conflicts.sort(key=lambda item: (item.control_step, _well_sort_key(item.well)))
    return tuple(conflicts)


def canonical_control_events(
    events: tuple[ControlEvent, ...] | list[ControlEvent],
) -> tuple[ControlEvent, ...]:
    conflicts = detect_control_conflicts(events)
    if conflicts:
        first = conflicts[0]
        raise ScheduleBuildError(
            f"конфликтующие управляющие события: скважина {first.well!r}, "
            f"control_step={first.control_step}, {first.kind.name}, "
            f"значения {first.values}"
        )
    unique: dict[tuple[int, str, EventKind, float | None], ControlEvent] = {}
    for event in events:
        unique.setdefault((event.control_step, event.well, event.kind, event.value), event)
    return tuple(
        sorted(
            unique.values(),
            key=lambda event: (
                event.control_step,
                _well_sort_key(event.well),
                _KIND_RANK[event.kind],
                event.kind.name,
            ),
        )
    )


def canonical_fixed_events(
    events: tuple[FixedDeckEvent, ...] | list[FixedDeckEvent],
) -> tuple[FixedDeckEvent, ...]:
    return tuple(sorted(events, key=lambda event: event.control_step))


def _status(token: str) -> OperatingStatus:
    try:
        return OperatingStatus[token]
    except KeyError as error:
        raise ScheduleBuildError(f"неизвестный статус скважины {token!r}") from error


def _prod_status_and_setpoint(args: tuple[str, ...]) -> tuple[OperatingStatus, float]:
    if len(args) < 6:
        raise ScheduleBuildError(f"WCONPROD: недостаточно полей {args!r}")
    return _status(args[0]), float(args[5])


def _inj_status_and_setpoint(args: tuple[str, ...]) -> tuple[OperatingStatus, float]:
    if len(args) < 4:
        raise ScheduleBuildError(f"WCONINJE: недостаточно полей {args!r}")
    return _status(args[1]), float(args[3])


def _block_records(raw: bytes) -> list[tuple[str, ...]]:
    lines = raw.splitlines(keepends=True)
    return block_records(lines, line_keyword(lines[0]))


def _apply_prefix_record(
    keyword: str,
    record: tuple[str, ...],
    roles: dict[str, Role],
    statuses: dict[str, OperatingStatus],
    setpoints: dict[str, float],
) -> None:
    well, *args = record
    if keyword == "WCONPROD":
        roles[well] = Role.PROD
        status, setpoint = _prod_status_and_setpoint(tuple(args))
    else:
        roles[well] = Role.INJ
        status, setpoint = _inj_status_and_setpoint(tuple(args))
    statuses[well] = status
    setpoints[well] = setpoint


def initial_state_from_prefix(
    parsed: ParsedSchedule, wells: tuple[str, ...]
) -> dict[str, WellState]:
    roles: dict[str, Role] = {}
    statuses: dict[str, OperatingStatus] = {}
    setpoints: dict[str, float] = {}
    for block in parsed.blocks:
        if block.keyword not in ("WCONPROD", "WCONINJE"):
            continue
        if block.event_date is None or block.event_date >= T0:
            continue
        for record in _block_records(block.raw):
            _apply_prefix_record(block.keyword, record, roles, statuses, setpoints)

    state: dict[str, WellState] = {}
    for well in wells:
        role = roles.get(well)
        if role is None:
            state[well] = WellState(
                availability=Availability.NOT_COMMISSIONED,
                role=Role.NONE,
                operating_status=OperatingStatus.SHUT,
                setpoint=0.0,
            )
            continue
        state[well] = WellState(
            availability=Availability.AVAILABLE,
            role=role,
            operating_status=statuses.get(well, OperatingStatus.SHUT),
            setpoint=setpoints.get(well, 0.0),
        )
    return state


def control_dates(parsed: ParsedSchedule) -> tuple[date, ...]:
    return parsed.dates[parsed.t0_deck_date_index :]


def _history_prefix(parsed: ParsedSchedule) -> tuple[str, ...]:
    return tuple(
        deck_date.isoformat() for deck_date in parsed.dates[: parsed.t0_deck_date_index]
    )


def _prefix_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def build_schedule(
    parsed: ParsedSchedule,
    raw: bytes,
    model: str = "Model_Z",
    provenance: str = "",
) -> Schedule:
    dates = control_dates(parsed)
    if not dates:
        raise ScheduleBuildError("после t0 в деке нет управляющих дат")
    n_control_dates = len(dates)
    n_intervals = n_control_dates - 1

    wells = deck_well_axis(raw)
    control_events = canonical_control_events(parsed.control_events)
    fixed_deck_events = canonical_fixed_events(parsed.fixed_deck_events)

    axis = set(wells)
    event_wells = {event.well for event in control_events} | {
        event.well for event in fixed_deck_events
    }
    unknown = sorted(event_wells - axis, key=_well_sort_key)
    if unknown:
        raise ScheduleBuildError(f"события по скважинам вне оси WELSPECS: {unknown}")

    for control_event in control_events:
        if control_event.control_step >= n_intervals:
            raise ScheduleBuildError(
                f"управляющее событие на control_step={control_event.control_step} "
                f"вне {n_intervals} интервалов дека"
            )

    initial_state = initial_state_from_prefix(parsed, wells)
    meta = ScheduleMeta(
        model=model,
        t0=dates[0],
        n_control_dates=n_control_dates,
        n_intervals=n_intervals,
        wells=wells,
        history_prefix_hash=_prefix_hash(_history_prefix(parsed)),
        fixed_events_hash=_prefix_hash(list(fixed_deck_events)),
        control_events_hash=_prefix_hash(list(control_events)),
        provenance=provenance,
    )
    return Schedule(
        meta=meta,
        initial_state=initial_state,
        fixed_deck_events=fixed_deck_events,
        control_events=control_events,
    )


def schedule_hash_parts(schedule: Schedule) -> str:
    return canonical_schedule_hash(
        schedule.initial_state, schedule.fixed_deck_events, schedule.control_events
    )


def load_schedule(path: str | Path, provenance: str = "") -> Schedule:
    raw = Path(path).read_bytes()
    try:
        parsed = parse_schedule(raw)
    except ScheduleParseError as error:
        raise ScheduleBuildError(f"дек {path!r} не разбирается: {error}") from error
    return build_schedule(parsed, raw, provenance=provenance)
