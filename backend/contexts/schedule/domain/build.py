from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from backend.core.contracts import (
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    Schedule,
    ScheduleMeta,
    T0,
    WellState,
)

from .canonical import (
    ScheduleCanonicalError,
    canonicalize,
    canonicalize_control_events,
    canonicalize_fixed_events,
    find_control_conflicts,
    hash_canonical_schedule,
)
from .lossless import ParsedSchedule, ScheduleParseError, parse_schedule
from .replay import ReplayError, replay_initial_state

_WELSPECS_RE = re.compile(rb"^WELSPECS\b(.*?)^/\s*$", re.MULTILINE | re.DOTALL)
_WELSPECS_WELL_RE = re.compile(rb"^\s*'([^']+)'", re.MULTILINE)


class ScheduleBuildError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ControlEventConflict:
    control_step: int
    well: str
    kind: EventKind
    values: tuple[float | None, ...]


def deck_well_axis(raw: bytes) -> tuple[str, ...]:
    match = _WELSPECS_RE.search(raw)
    if match is None:
        raise ScheduleBuildError("в деке нет блока WELSPECS: ось скважин неоткуда взять")
    wells = [well.decode("ascii") for well in _WELSPECS_WELL_RE.findall(match.group(1))]
    if not wells:
        raise ScheduleBuildError("WELSPECS не содержит ни одной скважины")
    # Лексикографический порядок — канон `bridge.OpmDeckEmitter.source_wells` (G2).
    unique = sorted(set(wells))
    if len(unique) != len(wells):
        raise ScheduleBuildError("WELSPECS содержит повторяющиеся скважины")
    return tuple(unique)


def detect_control_conflicts(
    events: tuple[ControlEvent, ...] | list[ControlEvent],
) -> tuple[ControlEventConflict, ...]:
    return tuple(
        ControlEventConflict(control_step=step, well=well, kind=kind, values=values)
        for step, well, kind, values in find_control_conflicts(events)
    )


def canonical_control_events(
    events: tuple[ControlEvent, ...] | list[ControlEvent],
) -> tuple[ControlEvent, ...]:
    try:
        return canonicalize_control_events(events)
    except ScheduleCanonicalError as error:
        raise ScheduleBuildError(str(error)) from error


def canonical_fixed_events(
    events: tuple[FixedDeckEvent, ...] | list[FixedDeckEvent],
) -> tuple[FixedDeckEvent, ...]:
    return canonicalize_fixed_events(events)


def initial_state_from_prefix(
    parsed: ParsedSchedule, wells: tuple[str, ...]
) -> dict[str, WellState]:
    try:
        return replay_initial_state(parsed, wells, T0)
    except ReplayError as error:
        raise ScheduleBuildError(f"replay истории не сошёлся: {error}") from error


def control_dates(parsed: ParsedSchedule) -> tuple[date, ...]:
    return parsed.dates[parsed.t0_deck_date_index :]


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
    unknown = sorted(event_wells - axis)
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
        provenance=provenance,
    )
    schedule = Schedule(
        meta=meta,
        initial_state=initial_state,
        fixed_deck_events=fixed_deck_events,
        control_events=control_events,
    )
    try:
        return canonicalize(schedule)
    except ScheduleCanonicalError as error:
        raise ScheduleBuildError(str(error)) from error


def schedule_hash_parts(schedule: Schedule) -> str:
    return hash_canonical_schedule(schedule)


def load_schedule(path: str | Path, provenance: str = "") -> Schedule:
    raw = Path(path).read_bytes()
    try:
        parsed = parse_schedule(raw)
    except ScheduleParseError as error:
        raise ScheduleBuildError(f"дек {path!r} не разбирается: {error}") from error
    return build_schedule(parsed, raw, provenance=provenance)
