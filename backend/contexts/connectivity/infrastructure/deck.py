from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from backend.contexts.connectivity.domain.deck_schedule import DeckSchedule, DeckWellRecord
from backend.contexts.schedule.domain.schedule import OperatingStatus, Role

__all__ = ["DeckSchedule", "DeckWellRecord", "parse_deck_schedule"]

MONTHS: dict[str, int] = {
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

_DATES = "DATES"
_WELSPECS = "WELSPECS"
_WCONPROD = "WCONPROD"
_WCONINJE = "WCONINJE"
_ROLE_KEYWORDS = (_WCONPROD, _WCONINJE)
_STATUS = {"OPEN": OperatingStatus.OPEN, "SHUT": OperatingStatus.SHUT}
_PROD_STATUS_FIELD = 1
_PROD_RATE_FIELD = 6
_INJ_STATUS_FIELD = 2
_INJ_RATE_FIELD = 4



def _parse_date(line: str) -> date:
    day, month, year = line.strip().strip("/").split()
    key = month.upper()
    if key not in MONTHS:
        raise ValueError(f"unrecognised month in DATES: {month}")
    return date(int(year), MONTHS[key], int(day))


def _fields(row: str) -> list[str]:
    return [f for f in re.split(r"\s+", row.strip()) if f]


def _well_of(row: str) -> str:
    parts = row.split("'")
    if len(parts) < 3:
        raise ValueError(f"a row without a well identifier: {row}")
    return parts[1]


def _block_rows(lines: list[str], start: int) -> tuple[list[str], int]:
    rows: list[str] = []
    cursor = start
    while cursor < len(lines):
        row = lines[cursor].strip()
        if row == "/":
            break
        if row.startswith("'") or (row and not row.startswith("--")):
            if row.startswith("'"):
                rows.append(row)
        cursor += 1
    return rows, cursor


def _record(
    keyword: str, deck_date_index: int, row: str
) -> DeckWellRecord:
    parts = _fields(row)
    well = _well_of(row)
    if keyword == _WCONPROD:
        status_token = parts[_PROD_STATUS_FIELD].strip("'").upper()
        rate_token = parts[_PROD_RATE_FIELD]
        role = Role.PROD
    else:
        status_token = parts[_INJ_STATUS_FIELD].strip("'").upper()
        rate_token = parts[_INJ_RATE_FIELD]
        role = Role.INJ
    if status_token not in _STATUS:
        raise ValueError(f"{keyword}: unrecognised status {status_token}")
    setpoint = 0.0 if rate_token.endswith("*") else float(rate_token)
    return DeckWellRecord(
        deck_date_index=deck_date_index,
        well=well,
        role=role,
        operating_status=_STATUS[status_token],
        setpoint_m3_per_day=setpoint,
    )


def parse_deck_schedule(path: Path) -> DeckSchedule:
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    dates: list[date] = []
    wells: list[str] = []
    records: list[DeckWellRecord] = []
    cursor = 0
    deck_date_index = -1
    while cursor < len(lines):
        token = lines[cursor].strip()
        if token == _DATES:
            deck_date_index += 1
            dates.append(_parse_date(lines[cursor + 1]))
        elif token == _WELSPECS:
            rows, cursor = _block_rows(lines, cursor + 1)
            wells.extend(_well_of(row) for row in rows)
        elif token in _ROLE_KEYWORDS:
            if deck_date_index < 0:
                raise ValueError(f"{token} precedes the first DATES: the deck time axis is undefined")
            rows, cursor = _block_rows(lines, cursor + 1)
            records.extend(_record(token, deck_date_index, row) for row in rows)
        cursor += 1
    return DeckSchedule(
        dates=tuple(dates),
        wells=tuple(sorted(set(wells))),
        records=tuple(records),
    )
