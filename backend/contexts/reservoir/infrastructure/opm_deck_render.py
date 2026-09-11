from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from backend.contexts.reservoir.domain.errors import OpmDeckError
from backend.contexts.schedule.domain.schedule import (
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    N_INTERVALS,
    Schedule,
    T0,
)
from backend.contexts.schedule.domain.lossless import LosslessBlock, ParsedSchedule, parse_schedule
from backend.contexts.reservoir.infrastructure.opm_deck_files import (
    _MODEL_DATA,
    _SCHEDULE_INCLUDE,
    EmittedSchedule,
    _WellControl,
    _resolve_opm_schedule_template,
)

def _format_number(value: float) -> str:
    return format(value, ".15g")


def _render_block(keyword: str, records: Iterable[str]) -> bytes:
    body = "".join(f" {record} /\n" for record in records)
    return f"\n{keyword}\n{body}/\n".encode("ascii")


def _render_fixed_wcon(events: Iterable[FixedDeckEvent], operator: str) -> bytes:
    records: list[str] = []
    for event in events:
        args = list(event.raw_args)
        quoted = 2 if operator == "WCONPROD" else 3
        if len(args) < quoted:
            raise OpmDeckError(f"{operator} {event.well!r}: incomplete fixed record")
        rendered_args = [
            f"'{token}'" if index < quoted else token
            for index, token in enumerate(args)
        ]
        records.append(f"'{event.well}' " + " ".join(rendered_args))
    return _render_block(operator, records) if records else b""


def _group_controls(events: Iterable[ControlEvent], step: int) -> tuple[_WellControl, ...]:
    by_well: dict[str, list[ControlEvent]] = defaultdict(list)
    for event in events:
        by_well[event.well].append(event)

    controls: list[_WellControl] = []
    for well in sorted(by_well):
        well_events = by_well[well]
        kinds = [event.kind for event in well_events]
        convert = EventKind.CONVERT_INJ in kinds
        if kinds.count(EventKind.CONVERT_INJ) > 1:
            raise OpmDeckError(f"control_step={step}, well={well!r}: repeated CONVERT_INJ")
        targets = [
            event
            for event in well_events
            if event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE)
        ]
        statuses = [
            event for event in well_events if event.kind in (EventKind.OPEN, EventKind.SHUT)
        ]
        if not targets or not statuses:
            raise OpmDeckError(
                f"control_step={step}, well={well!r}: a dense layer requires "
                "a setpoint and a status"
            )
        if not convert and (len(targets) != 1 or len(statuses) != 1):
            raise OpmDeckError(
                f"control_step={step}, well={well!r}: conflicting setpoints or statuses"
            )
        target = targets[-1]
        status = statuses[-1]
        if convert:
            conversion_index = kinds.index(EventKind.CONVERT_INJ)
            target_index = well_events.index(target)
            status_index = well_events.index(status)
            if (
                target.kind is not EventKind.SET_RATE
                or target_index < conversion_index
                or status_index < conversion_index
            ):
                raise OpmDeckError(
                    f"control_step={step}, well={well!r}: after CONVERT_INJ "
                    "a SET_RATE and a final status are required"
                )
        if target.value is None:
            raise OpmDeckError(f"control_step={step}, well={well!r}: a setpoint without value")
        controls.append(
            _WellControl(
                well=well,
                target_kind=target.kind,
                value=target.value,
                status=status.kind,
            )
        )
    return tuple(controls)


def _render_controls(events: Iterable[ControlEvent], step: int) -> bytes:
    producers: list[str] = []
    injectors: list[str] = []
    for control in _group_controls(events, step):
        status = control.status.value
        value = _format_number(control.value)
        if control.target_kind is EventKind.SET_LRAT:
            producers.append(
                f"'{control.well}' '{status}' 'LRAT' 1* 1* 1* {value} 1* 50 1* 1*"
            )
        else:
            injectors.append(
                f"'{control.well}' 'WATER' '{status}' 'RATE' {value} 1* 300 1* 1*"
            )
    return _render_block("WCONPROD", producers) + _render_block("WCONINJE", injectors)


def _render_schedule_bytes(schedule: Schedule, template: ParsedSchedule) -> bytes:
    controls_by_step: dict[int, list[ControlEvent]] = defaultdict(list)
    fixed_wcon_by_step: dict[int, dict[str, list[FixedDeckEvent]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for event in schedule.control_events:
        controls_by_step[event.control_step].append(event)
    for event in schedule.fixed_deck_events:
        if event.operator in ("WCONPROD", "WCONINJE"):
            fixed_wcon_by_step[event.control_step][event.operator].append(event)

    chunks: list[bytes] = []
    active_step: int | None = None

    def flush(step: int | None) -> None:
        if step is None or not (0 <= step < N_INTERVALS):
            return
        fixed = fixed_wcon_by_step[step]
        chunks.append(_render_fixed_wcon(fixed["WCONPROD"], "WCONPROD"))
        chunks.append(_render_fixed_wcon(fixed["WCONINJE"], "WCONINJE"))
        chunks.append(_render_controls(controls_by_step[step], step))

    for chunk in template.chunks:
        if isinstance(chunk, bytes):
            chunks.append(chunk)
            continue
        block: LosslessBlock = chunk
        if block.keyword == "DATES":
            flush(active_step)
            active_step = block.control_step
            chunks.append(block.raw)
        elif active_step is None or active_step < 0:
            chunks.append(block.raw)
        elif block.keyword not in ("WCONPROD", "WCONINJE"):
            chunks.append(block.raw)
    flush(active_step)
    return b"".join(chunks)


def render_schedule_include(
    schedule: Schedule, model_dir: Path | str
) -> EmittedSchedule:
    resolved_dir = Path(model_dir).resolve()
    data_file = resolved_dir / _MODEL_DATA
    schedule_file = resolved_dir / _SCHEDULE_INCLUDE
    if not data_file.is_file() or not schedule_file.is_file():
        raise FileNotFoundError(
            f"{resolved_dir} must contain {_MODEL_DATA} and {_SCHEDULE_INCLUDE}"
        )
    source_bytes = schedule_file.read_bytes()
    source_parsed = parse_schedule(source_bytes)
    template, template_source = _resolve_opm_schedule_template(
        resolved_dir, source_bytes, source_parsed
    )
    raw = _render_schedule_bytes(schedule, template)
    return EmittedSchedule(
        raw=raw,
        content_hash=hashlib.sha256(raw).hexdigest(),
        model_dir=resolved_dir,
        opm_schedule_source=template_source,
    )


def _control_period_offset(parsed: ParsedSchedule) -> int:
    offset = 0
    for chunk in parsed.chunks:
        if isinstance(chunk, bytes):
            offset += len(chunk)
            continue
        if chunk.keyword == "DATES" and chunk.control_step == 0:
            return offset
        offset += len(chunk.raw)
    raise OpmDeckError(
        f"the emitted schedule has no control start date t0={T0}: "
        "there is nothing to carve the controlled period out of"
    )


def render_control_period_include(
    schedule: Schedule, model_dir: Path | str
) -> EmittedSchedule:
    full = render_schedule_include(schedule, model_dir)
    parsed = parse_schedule(full.raw)
    raw = full.raw[_control_period_offset(parsed) :]
    return EmittedSchedule(
        raw=raw,
        content_hash=hashlib.sha256(raw).hexdigest(),
        model_dir=full.model_dir,
        opm_schedule_source=full.opm_schedule_source,
    )


def render_submission_history(schedule: Schedule, model_dir: Path | str) -> bytes:
    full = render_schedule_include(schedule, model_dir)
    return full.raw[:_control_period_offset(parse_schedule(full.raw))]

