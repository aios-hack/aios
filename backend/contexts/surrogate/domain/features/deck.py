from __future__ import annotations

import math
import re
from datetime import date
from types import MappingProxyType
from typing import Mapping, Sequence

from backend.contexts.schedule.domain.schedule import (
    Availability,
    OperatingStatus,
    Role,
    T0,
)
from backend.contexts.surrogate.domain.errors import FeatureError
from backend.contexts.surrogate.domain.features.types import (
    HistoryTargets,
    _MutableState,
)


_TOKEN_RE = re.compile(rb"'([^']*)'|([^\s/]+)")
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _records(raw_block: bytes) -> list[tuple[str, ...]]:
    records: list[tuple[str, ...]] = []
    for line in raw_block.splitlines()[1:-1]:
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue
        if not body.endswith(b"/"):
            raise FeatureError(f"deck record does not end with '/': {body!r}")
        fields = []
        for match in _TOKEN_RE.finditer(body[:-1]):
            token = match.group(1) if match.group(1) is not None else match.group(2)
            try:
                fields.append(token.decode("ascii"))
            except UnicodeDecodeError as error:
                raise FeatureError("non-ASCII token in the schedule") from error
        if fields:
            records.append(tuple(fields))
    return records


def _blocks(raw: bytes) -> list[tuple[str, bytes]]:
    lines = raw.splitlines(keepends=True)
    result: list[tuple[str, bytes]] = []
    index = 0
    while index < len(lines):
        try:
            keyword = lines[index].strip().decode("ascii")
        except UnicodeDecodeError:
            index += 1
            continue
        if keyword not in {"DATES", "WCONPROD", "WCONINJE"}:
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() != b"/":
            end += 1
        if end == len(lines):
            raise FeatureError(f"{keyword}: unclosed block")
        result.append((keyword, b"".join(lines[index : end + 1])))
        index = end + 1
    return result


def _deck_date(raw_block: bytes) -> date:
    records = _records(raw_block)
    if len(records) != 1 or len(records[0]) != 3:
        raise FeatureError("DATES must contain exactly one date")
    day, month, year = records[0]
    try:
        return date(int(year), _MONTHS[month.upper()], int(day))
    except (KeyError, ValueError) as error:
        raise FeatureError(f"invalid date: {records[0]!r}") from error


def _status(value: str) -> OperatingStatus:
    try:
        return OperatingStatus[value]
    except KeyError as error:
        raise FeatureError(f"unknown well status {value!r}") from error


def _float(value: str, *, well: str) -> float:
    try:
        result = float(value)
    except ValueError as error:
        raise FeatureError(f"setpoint {well!r} is not a number: {value!r}") from error
    if not math.isfinite(result) or result < 0:
        raise FeatureError(f"invalid setpoint {well!r}: {value!r}")
    return result


def _state_from_wcon(keyword: str, record: tuple[str, ...]) -> tuple[str, _MutableState]:
    well = record[0]
    if keyword == "WCONPROD":
        if len(record) < 7 or record[2] != "LRAT":
            raise FeatureError(f"WCONPROD {well!r}: LRAT mode expected")
        return well, _MutableState(
            Availability.AVAILABLE,
            Role.PROD,
            _status(record[1]),
            _float(record[6], well=well),
        )
    if len(record) < 5 or record[1] != "WATER" or record[3] != "RATE":
        raise FeatureError(f"WCONINJE {well!r}: WATER/RATE expected")
    return well, _MutableState(
        Availability.AVAILABLE,
        Role.INJ,
        _status(record[2]),
        _float(record[4], well=well),
    )


def history_targets_from_deck(
    raw_schedule: bytes,
    wells: Sequence[str],
    *,
    t0: date = T0,
) -> tuple[date, Mapping[str, HistoryTargets]]:
    ordered_wells = tuple(wells)
    if len(set(ordered_wells)) != len(ordered_wells):
        raise FeatureError("the wells axis contains duplicates")
    states: dict[str, _MutableState] = {
        well: _MutableState(
            Availability.NOT_COMMISSIONED,
            Role.NONE,
            OperatingStatus.SHUT,
            0.0,
        )
        for well in ordered_wells
    }
    liquid = {well: 0.0 for well in ordered_wells}
    injection = {well: 0.0 for well in ordered_wells}
    event_count = {well: 0 for well in ordered_wells}
    history_start: date | None = None
    current_date: date | None = None

    for keyword, raw_block in _blocks(raw_schedule):
        if keyword == "DATES":
            next_date = _deck_date(raw_block)
            if history_start is None:
                history_start = next_date
            if current_date is not None:
                if next_date <= current_date:
                    raise FeatureError(f"DATES are not increasing: {current_date} -> {next_date}")
                interval_end = min(next_date, t0)
                if interval_end > current_date:
                    days = (interval_end - current_date).days
                    for well, state in states.items():
                        target = state.effective_target * days
                        if state.role is Role.PROD:
                            liquid[well] += target
                        elif state.role is Role.INJ:
                            injection[well] += target
            current_date = next_date
            if next_date >= t0:
                break
            continue

        if current_date is None or current_date >= t0:
            continue
        for record in _records(raw_block):
            well, state = _state_from_wcon(keyword, record)
            if well not in states:
                raise FeatureError(f"well {well!r} from the history is missing from the wells axis")
            states[well] = state
            event_count[well] += 1

    if history_start is None:
        raise FeatureError("the deck has no DATES")
    if current_date is None or current_date < t0:
        raise FeatureError(f"the deck does not reach t0={t0.isoformat()}")
    return history_start, MappingProxyType(
        {
            well: HistoryTargets(liquid[well], injection[well], event_count[well])
            for well in ordered_wells
        }
    )


__all__ = [
    "history_targets_from_deck",
]
