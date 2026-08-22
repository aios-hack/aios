"""ResponseLoader — читает бинарные артефакты OPM Flow в ResponseArtifact.

contracts/README.md §3, §6; docs/context/08_contracts.md §4.1.1, §4.3.

Формат SMSPEC/UNSMRY (ECLIPSE binary summary) в проекте нигде не документирован
и не разбирался раньше — всё, что реализовано ниже, проверено настоящими
прогонами OPM Flow 2026.04 (не документацией по памяти):

- Fortran unformatted record ``[4 байта BE длина][payload][4 байта BE длина]``,
  заголовок ключевого слова — всегда один такой record из 16 байт
  (``keyword(8s)+count(u32 BE)+type(4s)``), данные — один или несколько
  отдельных records, режутся по границе блока (105 элементов для CHAR, 1000
  для INTE/REAL/DOUB/LOGI — константы из ``opm-common/opm/io/eclipse/
  EclIOdata.hpp``, не придуманы).
- Порядок колонок ``SMSPEC``/``UNSMRY`` не совпадает с порядком объявления
  секции SUMMARY в деке (OPM переупорядочивает) — единственный надёжный
  способ найти колонку: ``(KEYWORDS[i], WGNAMES[i], NUMS[i])``. Для
  well-векторов ``NUMS[i]=0``, для connection-векторов (``COPT``/``COPR``)
  ``NUMS[i]`` — 1-based натуральный индекс ячейки, та же формула, что уже
  проверена в ``bridge.summary._grid_index``.
- ``UNSMRY`` — последовательность ``SEQHDR``/``MINISTEP``/``PARAMS``.
  ``SEQHDR`` инкрементируется на каждый report step (запрошенная
  DATES/TSTEP дата), но между двумя ``SEQHDR`` может быть несколько
  ``MINISTEP``/``PARAMS`` — солвер режет шаг для сходимости. Значение на
  report-дату — последний ``PARAMS`` перед следующим ``SEQHDR`` (или EOF).
  ``deck_date_index`` — порядковый номер группы ``SEQHDR`` (0-based), не
  разбор даты.
- ``WOMT``/``WOMR`` не читаются Flow 2026.04 (см. задачу 3) и
  восстанавливаются из ``COPT``/``COPR`` с плотностью PVTNUM подключения.

Полная методика проверки — журнал сессии; здесь описан только результат.
"""

from __future__ import annotations

import hashlib
import struct
from bisect import bisect_right
from dataclasses import dataclass
from math import isnan
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from backend.core.contracts import (
    ActiveControlMode,
    Availability,
    ControlEvent,
    EventKind,
    IntervalResponse,
    N_INTERVALS,
    OperatingStatus,
    ResponseArtifact,
    RunResult,
    RunStatus,
    Schedule,
    StateAtDate,
    canonical_bytes,
)
from backend.core.contracts.response import N_DECK_DATES

from .summary import _TOKEN_RE, SummaryPlan, _grid_index


class ResponseLoaderError(ValueError):
    """Артефакты RunResult нельзя превратить в корректный ResponseArtifact."""


# --- бинарный слой: Fortran-record reader, работает на любом ECLIPSE-файле ---

_ELEMENTS_PER_BLOCK = {"INTE": 1000, "REAL": 1000, "DOUB": 1000, "LOGI": 1000, "CHAR": 105}


def _iter_fortran_records(path: Path) -> Iterator[bytes]:
    """[len(u32 BE)][payload][len(u32 BE)] — Fortran unformatted sequential."""

    data = path.read_bytes()
    pos = 0
    size = len(data)
    while pos < size:
        (n,) = struct.unpack_from(">I", data, pos)
        pos += 4
        payload = data[pos : pos + n]
        pos += n
        (n2,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if n != n2:
            raise ResponseLoaderError(
                f"{path}: несовпадающие маркеры Fortran-записи на смещении {pos}"
            )
        yield payload


def _iter_keyword_arrays(records: Iterator[bytes]) -> Iterator[tuple[str, str, list]]:
    """(keyword, type, values) — по одному ключевому слову за раз.

    Данные могут занимать несколько records подряд (см. ``_ELEMENTS_PER_BLOCK``);
    все они собираются в один список до возврата.
    """

    for header in records:
        keyword = header[:8].decode("ascii").strip()
        (count,) = struct.unpack_from(">I", header, 8)
        arr_type = header[12:16].decode("ascii")
        values: list = []
        remaining = count
        while remaining > 0:
            block = next(records)
            if arr_type == "CHAR":
                n = len(block) // 8
                values.extend(
                    block[j * 8 : (j + 1) * 8].decode("ascii").rstrip() for j in range(n)
                )
            elif arr_type == "INTE":
                n = len(block) // 4
                values.extend(struct.unpack(f">{n}i", block))
            elif arr_type == "REAL":
                n = len(block) // 4
                values.extend(struct.unpack(f">{n}f", block))
            elif arr_type == "DOUB":
                n = len(block) // 8
                values.extend(struct.unpack(f">{n}d", block))
            else:
                raise ResponseLoaderError(f"{keyword!r}: неподдерживаемый тип {arr_type!r}")
            remaining -= n
        yield keyword, arr_type, values


@dataclass(frozen=True, slots=True)
class _SmSpecIndex:
    """Позиция каждой колонки PARAMS по (keyword, wgname, nums) + размер сетки."""

    n_vectors: int
    nx: int
    ny: int
    nz: int
    column: dict[tuple[str, str, int], int]


def _read_smspec(path: Path) -> _SmSpecIndex:
    arrays: dict[str, list] = {}
    for keyword, _arr_type, values in _iter_keyword_arrays(_iter_fortran_records(path)):
        arrays[keyword] = values
    missing = [key for key in ("KEYWORDS", "WGNAMES", "NUMS", "DIMENS") if key not in arrays]
    if missing:
        raise ResponseLoaderError(f"{path}: обязательные ключи SMSPEC отсутствуют: {missing}")
    keywords, wgnames, nums, dimens = (
        arrays["KEYWORDS"],
        arrays["WGNAMES"],
        arrays["NUMS"],
        arrays["DIMENS"],
    )
    if not (len(keywords) == len(wgnames) == len(nums)):
        raise ResponseLoaderError(f"{path}: KEYWORDS/WGNAMES/NUMS разной длины")
    if len(dimens) < 4:
        raise ResponseLoaderError(f"{path}: DIMENS короче ожидаемого")
    column = {
        (kw, wg, int(n)): index for index, (kw, wg, n) in enumerate(zip(keywords, wgnames, nums))
    }
    return _SmSpecIndex(
        n_vectors=len(keywords),
        nx=int(dimens[1]),
        ny=int(dimens[2]),
        nz=int(dimens[3]),
        column=column,
    )


def _read_unsmry_report_rows(path: Path, n_vectors: int) -> list[tuple[float, ...]]:
    """Один ряд PARAMS на report step — последний MINISTEP перед следующим SEQHDR."""

    rows: list[tuple[float, ...]] = []
    current: tuple[float, ...] | None = None
    seen_seqhdr = False
    for keyword, _arr_type, values in _iter_keyword_arrays(_iter_fortran_records(path)):
        if keyword == "SEQHDR":
            if seen_seqhdr:
                if current is None:
                    raise ResponseLoaderError(f"{path}: report step без PARAMS")
                rows.append(current)
                current = None
            seen_seqhdr = True
        elif keyword == "PARAMS":
            if len(values) != n_vectors:
                raise ResponseLoaderError(
                    f"{path}: PARAMS длиной {len(values)}, ожидалось {n_vectors}"
                )
            current = tuple(values)
    if not seen_seqhdr:
        raise ResponseLoaderError(f"{path}: не найдено ни одного SEQHDR")
    if current is None:
        raise ResponseLoaderError(f"{path}: последний report step без PARAMS")
    rows.append(current)
    return rows


# --- плотность PVTNUM: DENSITY из Model_Z_props.inc ---


def load_density_by_pvtnum(model_dir: Path | str) -> dict[int, float]:
    """Плотность нефти (кг/м³) по PVTNUM из DENSITY. §4.3: восстановление WOMT/WOMR."""

    props_path = Path(model_dir).resolve() / "Model_Z_props.inc"
    if not props_path.is_file():
        raise FileNotFoundError(props_path)
    lines = props_path.read_bytes().splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == b"DENSITY"]
    if len(starts) != 1:
        raise ResponseLoaderError(f"{props_path}: ожидался один блок DENSITY, найдено {len(starts)}")
    densities: list[float] = []
    for line in lines[starts[0] + 1 :]:
        if not line.strip():
            break  # пустая строка — конец блока
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue  # строка целиком комментарий (напр. шапка колонок) — не конец блока
        if not body.endswith(b"/"):
            raise ResponseLoaderError(f"{props_path}: запись DENSITY не закрыта '/': {body!r}")
        tokens = [
            (match.group(1) if match.group(1) is not None else match.group(2))
            for match in _TOKEN_RE.finditer(body[:-1])
        ]
        if not tokens:
            raise ResponseLoaderError(f"{props_path}: пустая запись DENSITY")
        densities.append(float(tokens[0].decode("ascii")))
    if not densities:
        raise ResponseLoaderError(f"{props_path}: DENSITY не содержит записей")
    return {pvtnum: density for pvtnum, density in enumerate(densities, start=1)}


# --- сборочный слой: report row + SummaryPlan + плотности -> значения по скважине ---

_KG_PER_TONNE = 1000.0


@dataclass(frozen=True, slots=True)
class _WellRow:
    liquid_rate: float
    injection_rate: float
    oil_rate: float
    thp: float
    bhp: float
    well_efficiency: float
    liquid_cum: float
    injection_cum: float
    oil_mass_cum: float
    wmctl: float | None


def _connections_by_well(summary_plan: SummaryPlan) -> dict[str, tuple]:
    grouped: dict[str, list] = {well: [] for well in summary_plan.wells}
    for connection in summary_plan.connections:
        grouped[connection.well].append(connection)
    return {well: tuple(items) for well, items in grouped.items()}


def _build_well_rows(
    smspec: _SmSpecIndex,
    report_rows: Sequence[tuple[float, ...]],
    summary_plan: SummaryPlan,
    density_by_pvtnum: Mapping[int, float],
) -> list[dict[str, _WellRow]]:
    connections_by_well = _connections_by_well(summary_plan)
    missing_density = {
        connection.pvt_region
        for connection in summary_plan.connections
        if connection.pvt_region not in density_by_pvtnum
    }
    if missing_density:
        raise ResponseLoaderError(f"нет плотности для PVTNUM {sorted(missing_density)}")

    well_columns: dict[str, dict[str, int | None]] = {}
    for well in summary_plan.wells:
        columns = {
            key: smspec.column.get((key, well, 0))
            for key in ("WLPR", "WWIR", "WBHP", "WTHP", "WEFF", "WLPT", "WWIT", "WMCTL")
        }
        for key, column in columns.items():
            if column is None and key != "WMCTL":
                raise ResponseLoaderError(f"{well}: вектор {key} отсутствует в SMSPEC")
        well_columns[well] = columns

    # Каждая запись — (колонка COPT, колонка COPR, плотность т/м³) для одного подключения.
    connection_columns: dict[str, list[tuple[int, int, float]]] = {}
    for well, connections in connections_by_well.items():
        entries: list[tuple[int, int, float]] = []
        for connection in connections:
            nums = _grid_index(connection.i, connection.j, connection.k, smspec.nx, smspec.ny, smspec.nz) + 1
            copt_column = smspec.column.get(("COPT", well, nums))
            copr_column = smspec.column.get(("COPR", well, nums))
            if copt_column is None or copr_column is None:
                raise ResponseLoaderError(
                    f"{well}: подключение ({connection.i},{connection.j},{connection.k}) "
                    "не найдено в COPT/COPR по (well, NUMS)"
                )
            density_t_per_m3 = density_by_pvtnum[connection.pvt_region] / _KG_PER_TONNE
            entries.append((copt_column, copr_column, density_t_per_m3))
        connection_columns[well] = entries

    rows: list[dict[str, _WellRow]] = []
    for values in report_rows:
        row: dict[str, _WellRow] = {}
        for well in summary_plan.wells:
            columns = well_columns[well]
            entries = connection_columns[well]
            oil_mass_cum = sum(values[copt] * density for copt, _copr, density in entries)
            oil_rate = sum(values[copr] * density for _copt, copr, density in entries)
            wmctl_column = columns["WMCTL"]
            row[well] = _WellRow(
                liquid_rate=values[columns["WLPR"]],
                injection_rate=values[columns["WWIR"]],
                oil_rate=oil_rate,
                thp=values[columns["WTHP"]],
                bhp=values[columns["WBHP"]],
                well_efficiency=values[columns["WEFF"]],
                liquid_cum=values[columns["WLPT"]],
                injection_cum=values[columns["WWIT"]],
                oil_mass_cum=oil_mass_cum,
                wmctl=values[wmctl_column] if wmctl_column is not None else None,
            )
        rows.append(row)
    return rows


# --- Schedule: минимальная реплика состояния скважины, нужна только для
#     active_control_mode (WMCTL==0 -> SHUT/NOT_COMMISSIONED, и факт/цель
#     fallback, если WMCTL целиком недоступен). Не ProductionLedger — тот
#     считает деньги, это чужая задача; здесь только то, что нужно loader'у.

_RATE_CODES = frozenset({1, 2, 3, 4, 5, 9})  # ORAT/WRAT/GRAT/LRAT/RESV/CRAT
_PRESSURE_CODES = frozenset({6, 7})  # THP/BHP
_GROUP_CODE = -1
_NO_ACTIVE_CONTROL_CODE = 0  # SHUT/STOP/не найдена в динамике — Summary.cpp::well_control_mode
# -10 (WMCtlUnk) и любой другой нераспознанный код падают в UNKNOWN ниже, без
# отдельной константы — множество нераспознанных кодов не перечислимо.

_ACHIEVEMENT_THRESHOLD = 0.999
_PRODUCER_BHP_LIMIT_BAR = 50.0
_INJECTOR_BHP_LIMIT_BAR = 300.0
_BHP_LIMIT_TOLERANCE_BAR = 5.0  # [выбор]: точный допуск в 08_contracts.md §4.3 не назван числом


@dataclass(frozen=True, slots=True)
class _WellTimeline:
    """Состояние скважины по Schedule на любой control_step 0…223 (или раньше)."""

    baseline_available: bool
    baseline_operating_status: OperatingStatus
    baseline_setpoint: float
    status_steps: tuple[int, ...]
    status_values: tuple[OperatingStatus, ...]
    setpoint_steps: tuple[int, ...]
    setpoint_values: tuple[float, ...]
    first_open_step: int | None

    def is_commissioned(self, control_step: int) -> bool:
        if self.baseline_available:
            return True
        return self.first_open_step is not None and self.first_open_step <= control_step

    def operating_status(self, control_step: int) -> OperatingStatus:
        index = bisect_right(self.status_steps, control_step) - 1
        if index >= 0:
            return self.status_values[index]
        return self.baseline_operating_status

    def setpoint(self, control_step: int) -> float:
        index = bisect_right(self.setpoint_steps, control_step) - 1
        if index >= 0:
            return self.setpoint_values[index]
        return self.baseline_setpoint


def _build_well_timelines(schedule: Schedule) -> dict[str, _WellTimeline]:
    events_by_well: dict[str, list[ControlEvent]] = {}
    for event in schedule.control_events:
        events_by_well.setdefault(event.well, []).append(event)

    wells = set(schedule.initial_state) | set(events_by_well)
    timelines: dict[str, _WellTimeline] = {}
    for well in wells:
        baseline = schedule.initial_state.get(well)
        events = sorted(events_by_well.get(well, ()), key=lambda event: event.control_step)
        status_steps: list[int] = []
        status_values: list[OperatingStatus] = []
        setpoint_steps: list[int] = []
        setpoint_values: list[float] = []
        first_open: int | None = None
        for event in events:
            if event.kind is EventKind.OPEN:
                status_steps.append(event.control_step)
                status_values.append(OperatingStatus.OPEN)
                if first_open is None:
                    first_open = event.control_step
            elif event.kind is EventKind.SHUT:
                status_steps.append(event.control_step)
                status_values.append(OperatingStatus.SHUT)
            elif event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
                setpoint_steps.append(event.control_step)
                setpoint_values.append(event.value if event.value is not None else 0.0)
        timelines[well] = _WellTimeline(
            baseline_available=(baseline is not None and baseline.availability is Availability.AVAILABLE),
            baseline_operating_status=(
                baseline.operating_status if baseline is not None else OperatingStatus.SHUT
            ),
            baseline_setpoint=(baseline.setpoint if baseline is not None else 0.0),
            status_steps=tuple(status_steps),
            status_values=tuple(status_values),
            setpoint_steps=tuple(setpoint_steps),
            setpoint_values=tuple(setpoint_values),
            first_open_step=first_open,
        )
    return timelines


def _control_step_for_date(deck_date_index: int) -> int | None:
    """control_step, чьё решение действует на эту дату; None — до начала горизонта (§1.2)."""

    if deck_date_index < 146:
        return None
    return deck_date_index - 147  # -1 (ровно StateAtDate[146]) .. 223


def _fallback_control_mode(
    *,
    commissioned: bool,
    operating_status: OperatingStatus,
    setpoint: float,
    liquid_rate: float,
    injection_rate: float,
    bhp: float,
) -> ActiveControlMode:
    """§4.3: правило факт/цель, применяется только когда WMCTL целиком недоступен."""

    if not commissioned:
        return ActiveControlMode.NOT_COMMISSIONED
    if operating_status is OperatingStatus.SHUT:
        return ActiveControlMode.SHUT
    if setpoint <= 0:
        return ActiveControlMode.UNKNOWN
    is_injector = injection_rate > 0
    actual = injection_rate if is_injector else liquid_rate
    ratio = actual / setpoint
    limit = _INJECTOR_BHP_LIMIT_BAR if is_injector else _PRODUCER_BHP_LIMIT_BAR
    near_limit = abs(bhp - limit) <= _BHP_LIMIT_TOLERANCE_BAR
    if ratio < _ACHIEVEMENT_THRESHOLD and near_limit:
        return ActiveControlMode.BHP_LIMITED
    return ActiveControlMode.RATE_TARGET


def _resolve_control_mode(
    well: str,
    deck_date_index: int,
    well_row: _WellRow,
    timelines: Mapping[str, _WellTimeline],
) -> ActiveControlMode:
    control_step = _control_step_for_date(deck_date_index)
    timeline = timelines.get(well)
    commissioned = (
        True if control_step is None or timeline is None else timeline.is_commissioned(control_step)
    )

    if well_row.wmctl is not None:
        code = round(well_row.wmctl)
        if code in _RATE_CODES or code == _GROUP_CODE:
            return ActiveControlMode.RATE_TARGET
        if code in _PRESSURE_CODES:
            return ActiveControlMode.BHP_LIMITED
        if code == _NO_ACTIVE_CONTROL_CODE:
            return ActiveControlMode.SHUT if commissioned else ActiveControlMode.NOT_COMMISSIONED
        return ActiveControlMode.UNKNOWN  # -10 (WMCtlUnk) или нераспознанный код

    if control_step is None or timeline is None:
        return ActiveControlMode.UNKNOWN
    return _fallback_control_mode(
        commissioned=commissioned,
        operating_status=timeline.operating_status(control_step),
        setpoint=timeline.setpoint(control_step),
        liquid_rate=well_row.liquid_rate,
        injection_rate=well_row.injection_rate,
        bhp=well_row.bhp,
    )


# --- контрактный слой: здесь и только здесь проверяются оси 371/224 ---


def _build_state_at_date(
    report_rows: list[dict[str, _WellRow]],
    wells: Sequence[str],
    schedule: Schedule,
) -> tuple[StateAtDate, ...]:
    if len(report_rows) != N_DECK_DATES:
        raise ResponseLoaderError(
            f"UNSMRY даёт {len(report_rows)} report step(ов), контракт требует {N_DECK_DATES}"
        )
    timelines = _build_well_timelines(schedule)
    result: list[StateAtDate] = []
    for well in wells:
        for deck_date_index in range(N_DECK_DATES):
            well_row = report_rows[deck_date_index][well]
            mode = _resolve_control_mode(well, deck_date_index, well_row, timelines)
            result.append(
                StateAtDate(
                    deck_date_index=deck_date_index,
                    well=well,
                    liquid_rate=well_row.liquid_rate,
                    oil_rate=well_row.oil_rate,
                    injection_rate=well_row.injection_rate,
                    thp=well_row.thp,
                    bhp=well_row.bhp,
                    well_efficiency=well_row.well_efficiency,
                    active_control_mode=mode,
                )
            )
    return tuple(result)


def _build_interval_response(
    report_rows: list[dict[str, _WellRow]],
    wells: Sequence[str],
) -> tuple[IntervalResponse, ...]:
    if len(report_rows) != N_DECK_DATES:
        raise ResponseLoaderError(
            f"UNSMRY даёт {len(report_rows)} report step(ов), контракт требует {N_DECK_DATES}"
        )
    result: list[IntervalResponse] = []
    for well in wells:
        oil_mass_cum = [report_rows[d][well].oil_mass_cum for d in range(N_DECK_DATES)]
        liquid_cum = [report_rows[d][well].liquid_cum for d in range(N_DECK_DATES)]
        injection_cum = [report_rows[d][well].injection_cum for d in range(N_DECK_DATES)]
        # Шаг 1 (§4.1.1): raw_diff[i] = cum[i+1]-cum[i], i=0..369, строго внутри скважины;
        # терминальная строка i=370 в raw_diff не входит.
        oil_mass_diff = [oil_mass_cum[i + 1] - oil_mass_cum[i] for i in range(N_DECK_DATES - 1)]
        liquid_diff = [liquid_cum[i + 1] - liquid_cum[i] for i in range(N_DECK_DATES - 1)]
        injection_diff = [injection_cum[i + 1] - injection_cum[i] for i in range(N_DECK_DATES - 1)]
        # Шаг 2: IntervalResponse[k] = raw_diff[146+k], k=0..223 — простая переиндексация.
        for k in range(N_INTERVALS):
            i = 146 + k
            result.append(
                IntervalResponse(
                    control_step=k,
                    well=well,
                    oil_mass_delta=oil_mass_diff[i],
                    liquid_volume_delta=liquid_diff[i],
                    injection_volume_delta=injection_diff[i],
                )
            )
    return tuple(result)


_NUMERIC_STATE_FIELDS = ("liquid_rate", "oil_rate", "injection_rate", "thp", "bhp", "well_efficiency")
_NUMERIC_INTERVAL_FIELDS = ("oil_mass_delta", "liquid_volume_delta", "injection_volume_delta")


def _check_no_nan(
    state_at_date: tuple[StateAtDate, ...],
    interval_response: tuple[IntervalResponse, ...],
) -> None:
    for state in state_at_date:
        for field in _NUMERIC_STATE_FIELDS:
            if isnan(getattr(state, field)):
                raise ResponseLoaderError(
                    f"NaN в StateAtDate[{state.deck_date_index}, {state.well}].{field}"
                )
    for interval in interval_response:
        for field in _NUMERIC_INTERVAL_FIELDS:
            if isnan(getattr(interval, field)):
                raise ResponseLoaderError(
                    f"NaN в IntervalResponse[{interval.control_step}, {interval.well}].{field}"
                )


def _find_artifact(paths: Sequence[str], suffix: str) -> Path:
    matches = [Path(path) for path in paths if path.upper().endswith(suffix)]
    if len(matches) != 1:
        raise ResponseLoaderError(
            f"ожидался ровно один артефакт *{suffix}, найдено {len(matches)}: {matches}"
        )
    return matches[0]


class ResponseLoader:
    """Читает SMSPEC/UNSMRY успешного RunResult в ResponseArtifact.

    contracts/README.md §3, §6. Неуспешный ``RunResult`` не может дать
    отклик — падает сразу, не пытается угадать частичный результат.
    """

    def load(
        self,
        run_result: RunResult,
        summary_plan: SummaryPlan,
        schedule: Schedule,
        density_by_pvtnum: Mapping[int, float],
    ) -> ResponseArtifact:
        if run_result.status is not RunStatus.OK:
            raise ResponseLoaderError(
                f"RunResult {run_result.run_id!r} не OK ({run_result.status}): "
                "неуспешный прогон не выдаётся за корректный отклик"
            )

        smspec_path = _find_artifact(run_result.artifacts, "SMSPEC")
        unsmry_path = _find_artifact(run_result.artifacts, "UNSMRY")

        smspec = _read_smspec(smspec_path)
        report_rows_raw = _read_unsmry_report_rows(unsmry_path, smspec.n_vectors)
        well_rows = _build_well_rows(smspec, report_rows_raw, summary_plan, density_by_pvtnum)

        state_at_date = _build_state_at_date(well_rows, summary_plan.wells, schedule)
        interval_response = _build_interval_response(well_rows, summary_plan.wells)

        _check_no_nan(state_at_date, interval_response)

        response_hash = hashlib.sha256(
            canonical_bytes(
                {"state_at_date": state_at_date, "interval_response": interval_response}
            )
        ).hexdigest()

        return ResponseArtifact(
            source_run_id=run_result.run_id,
            response_hash=response_hash,
            state_at_date=state_at_date,
            interval_response=interval_response,
        )
