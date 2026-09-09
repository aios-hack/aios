from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from backend.core.contracts import (
    N_CONTROL_DATES,
    N_INTERVALS,
    T0,
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    Role,
    Schedule,
    SummarySpec,
    WellState,
)
from backend.domain.schedule import LosslessBlock, ParsedSchedule, parse_schedule

from .summary import (
    RegionPlan,
    SummaryPlan,
    SummaryPlanError,
    _expand_integers,
    _keyword_payload,
    build_region_plan,
    build_summary_plan,
    render_region_report_array,
    render_region_summary_include,
    render_summary_include,
)


_MODEL_DATA = "Model_Z.data"
_SCHEDULE_INCLUDE = "Model_Z_sch.inc"
_SUMMARY_INCLUDE = "Model_Z_summary.inc"
_REGIONS_INCLUDE = "Model_Z_regs.inc"
_INPUT_SUFFIXES = frozenset({".data", ".inc"})
_TOKEN_RE = re.compile(rb"'([^']*)'|([^\s/]+)")
_UTF8_BOM = b"\xef\xbb\xbf"
_OPM_UNSUPPORTED_GRID_KEYWORDS = (b"ARRZONE", b"ARRZONE_4")

DIAGNOSTIC_MARKER_NAME = "AIOS_DIAGNOSTIC_DECK"
DIAGNOSTIC_DECK_BANNER = (
    "-- AIOS DIAGNOSTIC DECK: NOT FOR SUBMISSION.\n"
    "-- FIPNUM is assembled from FIP_ZONE and RPR is requested per region so\n"
    "-- that regional pressure can be measured. The submitted deck carries\n"
    "-- neither array; a run of this deck is a measurement, not a delivery.\n"
)
DIAGNOSTIC_MARKER_TEXT = (
    "AIOS diagnostic deck.\n"
    "\n"
    "Дек собран для замера регионального пластового давления: FIPNUM собран "
    "из FIP_ZONE, в SUMMARY запрошен RPR по каждому размеченному региону.\n"
    "\n"
    "Этот дек не идёт в сдачу. Сдаваемое расписание им не меняется — "
    "управляющий и фиксированный слои те же, отличается только отчётность.\n"
)


class OpmDeckError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EmittedOpmDeck:
    data_file: Path
    schedule_file: Path
    summary_file: Path
    summary_plan: SummaryPlan
    input_files: tuple[Path, ...]
    content_hash_opm: str
    diagnostic: bool = False
    region_plan: RegionPlan | None = None
    regions_file: Path | None = None
    diagnostic_marker_file: Path | None = None


@dataclass(frozen=True, slots=True)
class EmittedSchedule:
    raw: bytes
    content_hash: str
    model_dir: Path
    opm_schedule_source: Path | None


@dataclass(frozen=True, slots=True)
class _WellControl:
    well: str
    target_kind: EventKind
    value: float
    status: EventKind


def _block_records(raw_block: bytes) -> tuple[tuple[str, ...], ...]:
    records: list[tuple[str, ...]] = []
    lines = raw_block.splitlines()
    for line in lines[1:-1]:
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue
        if not body.endswith(b"/"):
            raise OpmDeckError(f"запись блока не заканчивается '/': {body!r}")
        fields = []
        for match in _TOKEN_RE.finditer(body[:-1]):
            token = match.group(1) if match.group(1) is not None else match.group(2)
            try:
                fields.append(token.decode("ascii"))
            except UnicodeDecodeError as error:
                raise OpmDeckError("идентификатор WELSPECS должен быть ASCII") from error
        records.append(tuple(fields))
    return tuple(records)


def _raw_keyword_block(raw: bytes, keyword: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    matches: list[bytes] = []
    for index, line in enumerate(lines):
        if line.strip() != keyword:
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() != b"/":
            end += 1
        if end == len(lines):
            raise OpmDeckError(f"{keyword.decode()}: блок не закрыт")
        matches.append(b"".join(lines[index : end + 1]))
    if len(matches) != 1:
        raise OpmDeckError(
            f"ожидался один блок {keyword.decode()}, найдено {len(matches)}"
        )
    return matches[0]


def _strip_keyword_records(raw: bytes, keywords: tuple[bytes, ...]) -> bytes:
    lines = raw.splitlines(keepends=True)
    output: list[bytes] = []
    index = 0
    while index < len(lines):
        keyword = lines[index].strip()
        if keyword not in keywords:
            output.append(lines[index])
            index += 1
            continue
        start = index
        index += 1
        while index < len(lines) and lines[index].strip() != b"/":
            index += 1
        if index == len(lines):
            raise OpmDeckError(f"{keyword.decode()}: блок не закрыт")
        index += 1
        output.append(
            b"-- OPM compatibility: removed tNavigator-only "
            + keyword
            + f" block from source lines {start + 1}..{index}.\n".encode("ascii")
        )
    return b"".join(output)


def _completion_activation_keys(parsed: ParsedSchedule) -> set[tuple[int, str]]:
    return {
        (event.control_step, event.well)
        for event in parsed.fixed_deck_events
        if event.operator in ("COMPDAT", "COMPDATMD")
    }


def _noncompletion_fixed_events(parsed: ParsedSchedule) -> tuple[FixedDeckEvent, ...]:
    return tuple(
        event
        for event in parsed.fixed_deck_events
        if event.operator not in ("COMPDAT", "COMPDATMD")
    )


def _resolve_opm_schedule_template(
    model_dir: Path,
    source_raw: bytes,
    source_parsed: ParsedSchedule,
) -> tuple[ParsedSchedule, Path | None]:
    has_md = any(block.keyword == "COMPDATMD" for block in source_parsed.blocks)
    has_tracks = re.search(rb"(?m)^WELLTRACK(?:\s|$)", source_raw) is not None
    if not has_md and not has_tracks:
        return source_parsed, None

    configured = os.environ.get("AIOS_COMPDAT_MODEL_DIR")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    workspace = model_dir.parents[2] if len(model_dir.parents) >= 3 else model_dir.parent
    candidates.extend(
        (
            workspace / "docs-src" / "models" / "Model_Z",
            workspace / "dataset-700" / "base_run" / "deck",
        )
    )
    source_welspecs = _raw_keyword_block(source_raw, b"WELSPECS")
    source_dimens = _expand_integers(
        _keyword_payload((model_dir / _MODEL_DATA).read_bytes(), b"DIMENS"),
        "DIMENS",
    )
    source_pvtnum = _expand_integers(
        _keyword_payload(
            (model_dir / _REGIONS_INCLUDE).read_bytes().removeprefix(_UTF8_BOM),
            b"PVTNUM",
        ),
        "PVTNUM",
    )
    source_activation = _completion_activation_keys(source_parsed)
    source_other_fixed = _noncompletion_fixed_events(source_parsed)

    for candidate in candidates:
        candidate = candidate.resolve()
        schedule_file = candidate / _SCHEDULE_INCLUDE
        data_file = candidate / _MODEL_DATA
        regions_file = candidate / _REGIONS_INCLUDE
        if candidate == model_dir or not all(
            path.is_file() for path in (schedule_file, data_file, regions_file)
        ):
            continue
        candidate_raw = schedule_file.read_bytes().removeprefix(_UTF8_BOM)
        candidate_parsed = parse_schedule(candidate_raw)
        try:
            compatible = (
                _raw_keyword_block(candidate_raw, b"WELSPECS") == source_welspecs
                and _expand_integers(
                    _keyword_payload(data_file.read_bytes(), b"DIMENS"), "DIMENS"
                )
                == source_dimens
                and _expand_integers(
                    _keyword_payload(
                        regions_file.read_bytes().removeprefix(_UTF8_BOM), b"PVTNUM"
                    ),
                    "PVTNUM",
                )
                == source_pvtnum
            )
        except (OpmDeckError, SummaryPlanError):
            continue
        candidate_has_compdat = any(
            block.keyword == "COMPDAT" for block in candidate_parsed.blocks
        )
        candidate_has_md = any(
            block.keyword == "COMPDATMD" for block in candidate_parsed.blocks
        )
        candidate_has_tracks = (
            re.search(rb"(?m)^WELLTRACK(?:\s|$)", candidate_raw) is not None
        )
        if (
            compatible
            and candidate_has_compdat
            and not candidate_has_md
            and not candidate_has_tracks
            and candidate_parsed.dates == source_parsed.dates
            and _noncompletion_fixed_events(candidate_parsed) == source_other_fixed
            and _completion_activation_keys(candidate_parsed) == source_activation
        ):
            return candidate_parsed, candidate

    raise OpmDeckError(
        "WELLTRACK/COMPDATMD не поддерживаются Flow: не найдена проверенная "
        "эквивалентная COMPDAT-ревизия с совпадающими WELSPECS, датами, "
        "фиксированными событиями, DIMENS и PVTNUM"
    )


def bundle_hash(files: Iterable[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


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
            raise OpmDeckError(f"{operator} {event.well!r}: неполная фиксированная запись")
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
            raise OpmDeckError(f"control_step={step}, well={well!r}: повторный CONVERT_INJ")
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
                f"control_step={step}, well={well!r}: плотный слой требует "
                "уставку и статус"
            )
        if not convert and (len(targets) != 1 or len(statuses) != 1):
            raise OpmDeckError(
                f"control_step={step}, well={well!r}: конфликтующие уставки или статусы"
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
                    f"control_step={step}, well={well!r}: после CONVERT_INJ "
                    "требуются SET_RATE и конечный статус"
                )
        if target.value is None:
            raise OpmDeckError(f"control_step={step}, well={well!r}: уставка без value")
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
            f"в {resolved_dir} нужны {_MODEL_DATA} и {_SCHEDULE_INCLUDE}"
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


_MONTH_NAMES: tuple[str, ...] = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


def _seed_date(t0: date) -> date:
    if t0.month == 1:
        return date(t0.year - 1, 12, 1)
    return date(t0.year, t0.month - 1, 1)


def _render_dates(event_date: date) -> bytes:
    month = _MONTH_NAMES[event_date.month - 1]
    return (
        f"\nDATES\n {event_date.day:02d} {month} {event_date.year} /\n/\n"
    ).encode("ascii")


def _render_initial_state(
    wells: Sequence[str], initial_state: Mapping[str, WellState]
) -> bytes:
    producers: list[str] = []
    injectors: list[str] = []
    for well in wells:
        state = initial_state.get(well)
        if state is None:
            raise OpmDeckError(
                f"начальное состояние не задано для скважины {well!r}: "
                "управляемый период нельзя описать без состояния на t0"
            )
        if state.availability is not Availability.AVAILABLE:
            continue
        status = state.operating_status.name
        value = _format_number(state.setpoint)
        if state.role is Role.PROD:
            producers.append(f"'{well}' '{status}' 'LRAT' 1* 1* 1* {value} 1* 50 1* 1*")
        elif state.role is Role.INJ:
            injectors.append(f"'{well}' 'WATER' '{status}' 'RATE' {value} 1* 300 1* 1*")
        else:
            raise OpmDeckError(
                f"скважина {well!r} введена, но роль не определена: "
                "начальное состояние неполно"
            )
    return _render_block("WCONPROD", producers) + _render_block("WCONINJE", injectors)


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
        f"в эмитированном расписании нет даты начала управления t0={T0}: "
        "управляемый период выделить не из чего"
    )


def _deck_preamble(parsed: ParsedSchedule) -> bytes:
    head = parsed.chunks[0] if parsed.chunks else b""
    if not isinstance(head, bytes):
        raise OpmDeckError(
            "дек начинается с блока расписания: преамбулы с WELSPECS нет, "
            "ось скважин управляемого периода взять неоткуда"
        )
    if b"WELSPECS" not in head:
        raise OpmDeckError(
            "в преамбуле дека нет WELSPECS: ось скважин управляемого "
            "периода взять неоткуда"
        )
    return head


def render_control_period_include(
    schedule: Schedule, model_dir: Path | str
) -> EmittedSchedule:
    full = render_schedule_include(schedule, model_dir)
    parsed = parse_schedule(full.raw)
    raw = b"".join(
        (
            _deck_preamble(parsed),
            _render_dates(_seed_date(schedule.meta.t0)),
            _render_initial_state(schedule.meta.wells, schedule.initial_state),
            full.raw[_control_period_offset(parsed) :],
        )
    )
    return EmittedSchedule(
        raw=raw,
        content_hash=hashlib.sha256(raw).hexdigest(),
        model_dir=full.model_dir,
        opm_schedule_source=full.opm_schedule_source,
    )


class OpmDeckEmitter:
    def __init__(self, model_dir: Path | str) -> None:
        self.model_dir = Path(model_dir).resolve()
        self._data_file = self.model_dir / _MODEL_DATA
        self._schedule_file = self.model_dir / _SCHEDULE_INCLUDE
        if not self._data_file.is_file() or not self._schedule_file.is_file():
            raise FileNotFoundError(
                f"в {self.model_dir} нужны {_MODEL_DATA} и {_SCHEDULE_INCLUDE}"
            )
        self._source_schedule_bytes = self._schedule_file.read_bytes()
        self._parsed = parse_schedule(self._source_schedule_bytes)
        self._opm_parsed, self.opm_schedule_source = _resolve_opm_schedule_template(
            self.model_dir, self._source_schedule_bytes, self._parsed
        )
        welspecs = _raw_keyword_block(self._source_schedule_bytes, b"WELSPECS")
        self.source_wells = tuple(sorted(record[0] for record in _block_records(welspecs)))
        if len(self.source_wells) != 103 or len(set(self.source_wells)) != 103:
            raise OpmDeckError(
                f"Model_Z WELSPECS: ожидалось 103 уникальных скважины, "
                f"получено {len(set(self.source_wells))}"
            )

    def _validate(self, schedule: Schedule) -> None:
        meta = schedule.meta
        if meta.model != "Model_Z" or meta.t0 != T0:
            raise OpmDeckError(f"ожидался Model_Z с t0={T0}")
        if meta.n_control_dates != N_CONTROL_DATES or meta.n_intervals != N_INTERVALS:
            raise OpmDeckError(
                f"ожидались {N_CONTROL_DATES} дат и {N_INTERVALS} интервала"
            )
        if tuple(meta.wells) != self.source_wells:
            raise OpmDeckError(
                "ось Schedule.meta.wells должна содержать те же 103 скважины "
                "WELSPECS в лексикографическом порядке"
            )
        if tuple(schedule.fixed_deck_events) != self._parsed.fixed_deck_events:
            raise OpmDeckError("фиксированный слой Schedule отличается от Model_Z")
        unknown = {event.well for event in schedule.control_events} - set(self.source_wells)
        if unknown:
            raise OpmDeckError(f"управление адресует неизвестные скважины: {sorted(unknown)}")
        steps = {event.control_step for event in schedule.control_events}
        missing = set(range(N_INTERVALS)) - steps
        if missing:
            raise OpmDeckError(
                f"управляющий слой не материализован на всех 224 датах; "
                f"нет шагов {sorted(missing)}"
            )

    def emit(
        self,
        schedule: Schedule,
        destination: Path | str,
        *,
        summary_spec: SummarySpec | None = None,
        diagnostic_regions: bool = False,
    ) -> EmittedOpmDeck:
        self._validate(schedule)
        region_plan = (
            build_region_plan(self.model_dir) if diagnostic_regions else None
        )
        destination = Path(destination).resolve()
        if destination == self.model_dir or self.model_dir in destination.parents:
            raise OpmDeckError("destination не может совпадать с исходной Model_Z или лежать в ней")
        if destination.exists() and any(destination.iterdir()):
            raise FileExistsError(f"destination не пуст: {destination}")
        destination.mkdir(parents=True, exist_ok=True)

        source_files = tuple(
            sorted(
                path
                for path in self.model_dir.iterdir()
                if path.is_file() and path.suffix.lower() in _INPUT_SUFFIXES
            )
        )
        for source in source_files:
            target = destination / source.name
            source_raw = source.read_bytes()
            opm_raw = source_raw.removeprefix(_UTF8_BOM)
            if source.name == "Model_Z_grid.inc":
                target.write_bytes(
                    _strip_keyword_records(
                        opm_raw, _OPM_UNSUPPORTED_GRID_KEYWORDS
                    )
                )
            elif region_plan is not None and source.name == _REGIONS_INCLUDE:
                target.write_bytes(
                    opm_raw
                    + DIAGNOSTIC_DECK_BANNER.encode("ascii")
                    + render_region_report_array(region_plan)
                )
            elif region_plan is not None and source.name == _MODEL_DATA:
                target.write_bytes(
                    DIAGNOSTIC_DECK_BANNER.encode("ascii") + opm_raw
                )
            elif opm_raw != source_raw:
                target.write_bytes(opm_raw)
            else:
                shutil.copy2(source, target)

        emitted_schedule = destination / _SCHEDULE_INCLUDE
        emitted_schedule.write_bytes(
            render_schedule_include(schedule, self.model_dir).raw
        )
        summary_plan = build_summary_plan(
            self.model_dir,
            self.source_wells,
            spec=summary_spec,
        )
        emitted_summary = destination / _SUMMARY_INCLUDE
        summary_bytes = render_summary_include(summary_plan)
        if region_plan is not None:
            summary_bytes = (
                DIAGNOSTIC_DECK_BANNER.encode("ascii")
                + summary_bytes
                + render_region_summary_include(region_plan)
            )
        emitted_summary.write_bytes(summary_bytes)
        marker_file: Path | None = None
        if region_plan is not None:
            marker_file = destination / DIAGNOSTIC_MARKER_NAME
            marker_file.write_text(DIAGNOSTIC_MARKER_TEXT, encoding="utf-8")
        output_files = tuple(
            sorted(
                path
                for path in destination.iterdir()
                if path.is_file() and path.suffix.lower() in _INPUT_SUFFIXES
            )
        )
        return EmittedOpmDeck(
            data_file=destination / _MODEL_DATA,
            schedule_file=emitted_schedule,
            summary_file=emitted_summary,
            summary_plan=summary_plan,
            input_files=output_files,
            content_hash_opm=bundle_hash(output_files, destination),
            diagnostic=region_plan is not None,
            region_plan=region_plan,
            regions_file=(
                destination / _REGIONS_INCLUDE if region_plan is not None else None
            ),
            diagnostic_marker_file=marker_file,
        )
