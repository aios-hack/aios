
from __future__ import annotations

from backend.contexts.schedule.domain.errors import (
    ScheduleParseError,
)

import re
from dataclasses import dataclass
from datetime import date

from backend.contexts.schedule.domain.schedule import (
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    N_INTERVALS,
    T0,
)


_BLOCK_KEYWORDS = frozenset(
    {"DATES", "COMPDAT", "COMPDATMD", "WPIMULT", "WCONPROD", "WCONINJE"}
)
_FIXED_KEYWORDS = frozenset({"COMPDAT", "COMPDATMD", "WPIMULT"})
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
_TOKEN_RE = re.compile(rb"'([^']*)'|([^\s/]+)")


@dataclass(frozen=True, slots=True)
class LosslessBlock:
    keyword: str
    raw: bytes
    deck_date_index: int | None
    event_date: date | None
    control_step: int | None
    fixed_deck_events: tuple[FixedDeckEvent, ...] = ()
    control_events: tuple[ControlEvent, ...] = ()


LosslessChunk = bytes | LosslessBlock


@dataclass(frozen=True, slots=True)
class ParsedSchedule:
    chunks: tuple[LosslessChunk, ...]
    blocks: tuple[LosslessBlock, ...]
    dates: tuple[date, ...]
    t0_deck_date_index: int
    fixed_deck_events: tuple[FixedDeckEvent, ...]
    control_events: tuple[ControlEvent, ...]

    @property
    def fixed_blocks(self) -> tuple[LosslessBlock, ...]:
        return tuple(block for block in self.blocks if block.fixed_deck_events)


def emit_lossless(schedule: ParsedSchedule) -> bytes:
    return b"".join(
        chunk if isinstance(chunk, bytes) else chunk.raw for chunk in schedule.chunks
    )


def _ascii(raw: bytes, what: str) -> str:
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise ScheduleParseError(f"{what}: ASCII expected") from error


def line_keyword(line: bytes) -> str:
    return _ascii(line.strip(), "keyword")


def block_records(block_lines: list[bytes], keyword: str) -> list[tuple[str, ...]]:
    records: list[tuple[str, ...]] = []
    for line in block_lines[1:-1]:
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue
        if not body.endswith(b"/"):
            raise ScheduleParseError(
                f"{keyword}: the record does not end with '/': {body!r}"
            )
        fields: list[str] = []
        for match in _TOKEN_RE.finditer(body[:-1]):
            token = match.group(1) if match.group(1) is not None else match.group(2)
            fields.append(_ascii(token, f"{keyword}: token"))
        if not fields:
            raise ScheduleParseError(f"{keyword}: empty record")
        records.append(tuple(fields))
    return records


def _parse_date(records: list[tuple[str, ...]]) -> date:
    if len(records) != 1 or len(records[0]) != 3:
        raise ScheduleParseError("DATES must contain exactly one date")
    day, month, year = records[0]
    try:
        return date(int(year), _MONTHS[month.upper()], int(day))
    except (KeyError, TypeError, ValueError) as error:
        raise ScheduleParseError(
            f"invalid DATES date: {records[0]!r}"
        ) from error


def _status_event(control_step: int, well: str, status: str) -> ControlEvent:
    try:
        kind = EventKind[status]
    except KeyError as error:
        raise ScheduleParseError(
            f"WCON: unknown status {status!r}"
        ) from error
    if kind not in (EventKind.OPEN, EventKind.SHUT):
        raise ScheduleParseError(
            f"WCON: the status must be OPEN/SHUT, got {status!r}"
        )
    return ControlEvent(control_step=control_step, well=well, kind=kind)


def _float(value: str, keyword: str, well: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise ScheduleParseError(
            f"{keyword}: the setpoint of well {well!r} is not a number: "
            f"{value!r}"
        ) from error


def parse_schedule(raw: bytes) -> ParsedSchedule:
    if not isinstance(raw, bytes):
        raise TypeError(
            "parse_schedule takes bytes; read the file via Path.read_bytes()"
        )

    lines = raw.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    chunks: list[LosslessChunk] = []
    blocks: list[LosslessBlock] = []
    dates: list[date] = []
    fixed_events: list[FixedDeckEvent] = []
    control_events: list[ControlEvent] = []
    seen_wells: set[str] = set()
    roles: dict[str, str] = {}
    converted_wells: set[str] = set()
    t0_deck_date_index: int | None = None
    current_date: date | None = None
    current_deck_date_index: int | None = None

    i = 0
    segment_start = 0
    while i < len(lines):
        keyword = line_keyword(lines[i])
        if keyword not in _BLOCK_KEYWORDS:
            i += 1
            continue

        end_line = i + 1
        while end_line < len(lines) and lines[end_line].strip() != b"/":
            end_line += 1
        if end_line == len(lines):
            raise ScheduleParseError(
                f"{keyword}: the block is not closed by a separate '/' line"
            )

        block_start = offsets[i]
        block_end = offsets[end_line] + len(lines[end_line])
        if segment_start < block_start:
            chunks.append(raw[segment_start:block_start])
        block_raw = raw[block_start:block_end]
        parsed_records = block_records(lines[i : end_line + 1], keyword)

        block_fixed: list[FixedDeckEvent] = []
        block_control: list[ControlEvent] = []
        if keyword == "DATES":
            current_date = _parse_date(parsed_records)
            if dates and current_date <= dates[-1]:
                raise ScheduleParseError(
                    f"DATES are not increasing: {dates[-1]} -> {current_date}"
                )
            dates.append(current_date)
            current_deck_date_index = len(dates) - 1
            if current_date == T0:
                t0_deck_date_index = current_deck_date_index
        else:
            if current_date is None or current_deck_date_index is None:
                control_step = None
            elif current_date >= T0:
                if t0_deck_date_index is None:
                    raise ScheduleParseError(
                        f"DATES is missing the mandatory date t0={T0}"
                    )
                control_step = current_deck_date_index - t0_deck_date_index
            else:
                control_step = None

            if keyword in _FIXED_KEYWORDS and control_step is not None:
                for record in parsed_records:
                    well, *args = record
                    block_fixed.append(
                        FixedDeckEvent(
                            control_step=control_step,
                            well=well,
                            operator=keyword,
                            raw_args=tuple(args),
                        )
                    )

            if keyword in ("WCONPROD", "WCONINJE"):
                for record in parsed_records:
                    well = record[0]
                    is_first_appearance = well not in seen_wells
                    previous_role = roles.get(well)
                    seen_wells.add(well)

                    if keyword == "WCONPROD":
                        if len(record) < 7 or record[2] != "LRAT":
                            raise ScheduleParseError(
                                f"WCONPROD {well!r}: LRAT mode expected"
                            )
                        status = record[1]
                        value = _float(record[6], keyword, well)
                        new_role = "PROD"
                    else:
                        if len(record) < 5 or record[1] != "WATER" or record[3] != "RATE":
                            raise ScheduleParseError(
                                f"WCONINJE {well!r}: WATER phase and RATE "
                                f"mode expected"
                            )
                        status = record[2]
                        value = _float(record[4], keyword, well)
                        new_role = "INJ"

                    in_control_interval = (
                        control_step is not None and control_step < N_INTERVALS
                    )
                    if in_control_interval and is_first_appearance:
                        block_fixed.append(
                            FixedDeckEvent(
                                control_step=control_step,
                                well=well,
                                operator=keyword,
                                raw_args=tuple(record[1:]),
                            )
                        )
                    elif in_control_interval:
                        if keyword == "WCONPROD":
                            if previous_role == "INJ":
                                raise ScheduleParseError(
                                    f"{well!r}: the reverse conversion "
                                    f"INJ -> PROD is not expressible by the "
                                    f"contract"
                                )
                            block_control.append(
                                ControlEvent(
                                    control_step=control_step,
                                    well=well,
                                    kind=EventKind.SET_LRAT,
                                    value=value,
                                )
                            )
                        else:
                            if previous_role == "PROD" and well not in converted_wells:
                                block_control.append(
                                    ControlEvent(
                                        control_step=control_step,
                                        well=well,
                                        kind=EventKind.CONVERT_INJ,
                                    )
                                )
                                converted_wells.add(well)
                            block_control.append(
                                ControlEvent(
                                    control_step=control_step,
                                    well=well,
                                    kind=EventKind.SET_RATE,
                                    value=value,
                                )
                            )
                        block_control.append(_status_event(control_step, well, status))
                    roles[well] = new_role

        if keyword == "DATES":
            block_control_step = (
                current_deck_date_index - t0_deck_date_index
                if t0_deck_date_index is not None
                and current_deck_date_index is not None
                and current_date is not None
                and current_date >= T0
                else None
            )
        else:
            block_control_step = control_step

        block = LosslessBlock(
            keyword=keyword,
            raw=block_raw,
            deck_date_index=current_deck_date_index,
            event_date=current_date,
            control_step=block_control_step,
            fixed_deck_events=tuple(block_fixed),
            control_events=tuple(block_control),
        )
        blocks.append(block)
        chunks.append(block)
        fixed_events.extend(block_fixed)
        control_events.extend(block_control)

        segment_start = block_end
        i = end_line + 1

    if segment_start < len(raw):
        chunks.append(raw[segment_start:])
    if t0_deck_date_index is None:
        raise ScheduleParseError(f"DATES is missing the mandatory date t0={T0}")

    return ParsedSchedule(
        chunks=tuple(chunks),
        blocks=tuple(blocks),
        dates=tuple(dates),
        t0_deck_date_index=t0_deck_date_index,
        fixed_deck_events=tuple(fixed_events),
        control_events=tuple(control_events),
    )


_records = block_records
_line_token = line_keyword
