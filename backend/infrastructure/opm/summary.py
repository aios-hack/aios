"""План и OPM-представление секции SUMMARY для Model_Z."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.core.contracts import SummarySpec
from backend.domain.schedule import parse_schedule


_MODEL_DATA = "Model_Z.data"
_REGIONS_INCLUDE = "Model_Z_regs.inc"
_SCHEDULE_INCLUDE = "Model_Z_sch.inc"
_TOKEN_RE = re.compile(rb"'([^']*)'|([^\s/]+)")
_REPEAT_RE = re.compile(r"(\d+)\*(-?\d+)\Z")


class SummaryPlanError(ValueError):
    """Статика Model_Z не позволяет однозначно построить секцию SUMMARY."""


@dataclass(frozen=True, slots=True, order=True)
class SummaryConnection:
    """Уникальное подключение скважины и PVT-регион его ячейки."""

    well: str
    i: int
    j: int
    k: int
    pvt_region: int


@dataclass(frozen=True, slots=True)
class SummaryPlan:
    """Логический контракт плюс конкретные оси SUMMARY для одного дека."""

    spec: SummarySpec
    wells: tuple[str, ...]
    connections: tuple[SummaryConnection, ...]


def _keyword_payload(raw: bytes, keyword: bytes) -> tuple[str, ...]:
    """Вернуть токены первой записи после keyword до первого ``/``."""

    lines = raw.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == keyword]
    if len(starts) != 1:
        raise SummaryPlanError(
            f"ожидался один блок {keyword.decode()}, найдено {len(starts)}"
        )
    payload = bytearray()
    for line in lines[starts[0] + 1 :]:
        body = line.split(b"--", 1)[0]
        before, separator, _ = body.partition(b"/")
        payload.extend(b" ")
        payload.extend(before)
        if separator:
            break
    else:
        raise SummaryPlanError(f"{keyword.decode()}: запись не закрыта '/'")
    try:
        return tuple(payload.decode("ascii").split())
    except UnicodeDecodeError as error:
        raise SummaryPlanError(f"{keyword.decode()}: ожидался ASCII") from error


def _records(raw_block: bytes, keyword: str) -> tuple[tuple[str, ...], ...]:
    records: list[tuple[str, ...]] = []
    for line in raw_block.splitlines()[1:-1]:
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue
        if not body.endswith(b"/"):
            raise SummaryPlanError(f"{keyword}: запись не заканчивается '/': {body!r}")
        fields: list[str] = []
        for match in _TOKEN_RE.finditer(body[:-1]):
            token = match.group(1) if match.group(1) is not None else match.group(2)
            try:
                fields.append(token.decode("ascii"))
            except UnicodeDecodeError as error:
                raise SummaryPlanError(f"{keyword}: ожидался ASCII") from error
        records.append(tuple(fields))
    return tuple(records)


def _expand_integers(tokens: Iterable[str], keyword: str) -> tuple[int, ...]:
    values: list[int] = []
    for token in tokens:
        repeat = _REPEAT_RE.fullmatch(token)
        try:
            if repeat:
                count, value = map(int, repeat.groups())
                values.extend([value] * count)
            else:
                values.append(int(token))
        except ValueError as error:
            raise SummaryPlanError(f"{keyword}: нецелый токен {token!r}") from error
    return tuple(values)


def _grid_index(i: int, j: int, k: int, nx: int, ny: int, nz: int) -> int:
    if not (1 <= i <= nx and 1 <= j <= ny and 1 <= k <= nz):
        raise SummaryPlanError(
            f"COMPDAT: ячейка ({i}, {j}, {k}) вне DIMENS ({nx}, {ny}, {nz})"
        )
    return (k - 1) * nx * ny + (j - 1) * nx + (i - 1)


def build_summary_plan(
    model_dir: Path | str,
    wells: Iterable[str],
    spec: SummarySpec | None = None,
) -> SummaryPlan:
    """Развернуть все COMPDAT и связать подключения с PVTNUM ячеек."""

    model_dir = Path(model_dir).resolve()
    data_path = model_dir / _MODEL_DATA
    regions_path = model_dir / _REGIONS_INCLUDE
    schedule_path = model_dir / _SCHEDULE_INCLUDE
    for path in (data_path, regions_path, schedule_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    dimens = _expand_integers(_keyword_payload(data_path.read_bytes(), b"DIMENS"), "DIMENS")
    if len(dimens) != 3:
        raise SummaryPlanError(f"DIMENS: ожидалось 3 значения, получено {len(dimens)}")
    nx, ny, nz = dimens
    pvtnum = _expand_integers(
        _keyword_payload(regions_path.read_bytes(), b"PVTNUM"), "PVTNUM"
    )
    if len(pvtnum) != nx * ny * nz:
        raise SummaryPlanError(
            f"PVTNUM: ожидалось {nx * ny * nz} ячеек, получено {len(pvtnum)}"
        )

    well_axis = tuple(wells)
    if len(well_axis) != len(set(well_axis)) or well_axis != tuple(sorted(well_axis)):
        raise SummaryPlanError("ось wells должна быть уникальной и лексикографической")
    known_wells = set(well_axis)
    cells: set[tuple[str, int, int, int]] = set()
    parsed = parse_schedule(schedule_path.read_bytes())
    for block in parsed.blocks:
        if block.keyword != "COMPDAT":
            continue
        for record in _records(block.raw, "COMPDAT"):
            if len(record) < 5:
                raise SummaryPlanError(f"COMPDAT: неполная запись {record!r}")
            well = record[0]
            if well not in known_wells:
                raise SummaryPlanError(f"COMPDAT: неизвестная скважина {well!r}")
            try:
                i, j, k1, k2 = map(int, record[1:5])
            except ValueError as error:
                raise SummaryPlanError(f"COMPDAT {well!r}: нецелые I/J/K1/K2") from error
            if k1 > k2:
                raise SummaryPlanError(f"COMPDAT {well!r}: K1={k1} больше K2={k2}")
            cells.update((well, i, j, k) for k in range(k1, k2 + 1))

    cell_wells = {well for well, _, _, _ in cells}
    if cell_wells != known_wells:
        missing = sorted(known_wells - cell_wells)
        extra = sorted(cell_wells - known_wells)
        raise SummaryPlanError(
            f"оси WELSPECS и COMPDAT расходятся: без подключений={missing}, лишние={extra}"
        )

    connections: list[SummaryConnection] = []
    for well, i, j, k in sorted(cells):
        region = pvtnum[_grid_index(i, j, k, nx, ny, nz)]
        if region <= 0:
            raise SummaryPlanError(
                f"COMPDAT {well!r}: ячейка ({i}, {j}, {k}) неактивна по PVTNUM"
            )
        connections.append(SummaryConnection(well, i, j, k, region))

    region_counts = Counter(connection.pvt_region for connection in connections)
    if set(region_counts) != {1, 2}:
        raise SummaryPlanError(f"Model_Z: ожидались PVT-регионы 1 и 2, получено {region_counts}")
    return SummaryPlan(
        spec=spec if spec is not None else SummarySpec(),
        wells=well_axis,
        connections=tuple(connections),
    )


def render_summary_include(plan: SummaryPlan) -> bytes:
    """Сериализовать поддерживаемые Flow well/connection summary-векторы."""

    lines = [
        "-- Generated by bridge.summary; do not edit.\n",
        f"-- wells={len(plan.wells)} connections={len(plan.connections)}\n",
    ]
    for keyword in plan.spec.opm_well_keys:
        lines.append(f"\n{keyword}\n")
        lines.extend(f" '{well}'\n" for well in plan.wells)
        lines.append("/\n")
    for keyword in plan.spec.opm_connection_keys:
        lines.append(f"\n{keyword}\n")
        lines.extend(
            f" '{connection.well}' {connection.i} {connection.j} {connection.k} /\n"
            for connection in plan.connections
        )
        lines.append("/\n")
    return "".join(lines).encode("ascii")
