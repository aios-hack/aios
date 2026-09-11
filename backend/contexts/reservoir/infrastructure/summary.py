from __future__ import annotations

from backend.contexts.reservoir.domain.errors import (
    SummaryPlanError,
)

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.contexts.runs.domain.run_result import SummarySpec
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.shared.settings import Settings


_MODEL_DATA = "Model_Z.data"
_REGIONS_INCLUDE = "Model_Z_regs.inc"
_SCHEDULE_INCLUDE = "Model_Z_sch.inc"
_TOKEN_RE = re.compile(rb"'([^']*)'|([^\s/]+)")
_REPEAT_RE = re.compile(r"(\d+)\*(-?\d+)\Z")
REGION_MARKUP_KEYWORD = "FIP_ZONE"
REGION_REPORT_KEYWORD = "FIPNUM"
REGION_PRESSURE_KEY = "RPR"
REGION_VALUES_PER_LINE = 20


@dataclass(frozen=True, slots=True, order=True)
class SummaryConnection:
    well: str
    i: int
    j: int
    k: int
    pvt_region: int


@dataclass(frozen=True, slots=True)
class SummaryPlan:
    spec: SummarySpec
    wells: tuple[str, ...]
    connections: tuple[SummaryConnection, ...]


def _keyword_payload(raw: bytes, keyword: bytes) -> tuple[str, ...]:
    lines = raw.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == keyword]
    if len(starts) != 1:
        raise SummaryPlanError(
            f"expected one {keyword.decode()} block, found {len(starts)}"
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
        raise SummaryPlanError(f"{keyword.decode()}: record is not closed with '/'")
    try:
        return tuple(payload.decode("ascii").split())
    except UnicodeDecodeError as error:
        raise SummaryPlanError(f"{keyword.decode()}: expected ASCII") from error


def _records(raw_block: bytes, keyword: str) -> tuple[tuple[str, ...], ...]:
    records: list[tuple[str, ...]] = []
    for line in raw_block.splitlines()[1:-1]:
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue
        if not body.endswith(b"/"):
            raise SummaryPlanError(f"{keyword}: record does not end with '/': {body!r}")
        fields: list[str] = []
        for match in _TOKEN_RE.finditer(body[:-1]):
            token = match.group(1) if match.group(1) is not None else match.group(2)
            try:
                fields.append(token.decode("ascii"))
            except UnicodeDecodeError as error:
                raise SummaryPlanError(f"{keyword}: expected ASCII") from error
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
            raise SummaryPlanError(f"{keyword}: non-integer token {token!r}") from error
    return tuple(values)


def _grid_index(i: int, j: int, k: int, nx: int, ny: int, nz: int) -> int:
    if not (1 <= i <= nx and 1 <= j <= ny and 1 <= k <= nz):
        raise SummaryPlanError(
            f"COMPDAT: cell ({i}, {j}, {k}) is outside DIMENS ({nx}, {ny}, {nz})"
        )
    return (k - 1) * nx * ny + (j - 1) * nx + (i - 1)


def _compdat_cells(
    schedule_path: Path, known_wells: set[str]
) -> set[tuple[str, int, int, int]]:
    cells: set[tuple[str, int, int, int]] = set()
    parsed = parse_schedule(schedule_path.read_bytes())
    for block in parsed.blocks:
        if block.keyword != "COMPDAT":
            continue
        for record in _records(block.raw, "COMPDAT"):
            if len(record) < 5:
                raise SummaryPlanError(f"COMPDAT: incomplete record {record!r}")
            well = record[0]
            if well not in known_wells:
                raise SummaryPlanError(f"COMPDAT: unknown well {well!r}")
            try:
                i, j, k1, k2 = map(int, record[1:5])
            except ValueError as error:
                raise SummaryPlanError(f"COMPDAT {well!r}: non-integer I/J/K1/K2") from error
            if k1 > k2:
                raise SummaryPlanError(f"COMPDAT {well!r}: K1={k1} is greater than K2={k2}")
            cells.update((well, i, j, k) for k in range(k1, k2 + 1))
    return cells


def _equivalent_compdat_cells(
    model_dir: Path,
    known_wells: set[str],
    dimens: tuple[int, int, int],
    pvtnum: tuple[int, ...],
) -> set[tuple[str, int, int, int]]:
    configured = Settings.from_env().compdat_model_dir
    candidates = []
    if configured is not None:
        candidates.append(configured)
    workspace = model_dir.parents[2] if len(model_dir.parents) >= 3 else model_dir.parent
    candidates.extend(
        (
            workspace / "docs-src" / "models" / "Model_Z",
            workspace / "dataset-700" / "base_run" / "deck",
        )
    )
    for candidate in candidates:
        schedule = candidate / _SCHEDULE_INCLUDE
        data = candidate / _MODEL_DATA
        regions = candidate / _REGIONS_INCLUDE
        if not all(path.is_file() for path in (schedule, data, regions)):
            continue
        source_dimens = _expand_integers(_keyword_payload(data.read_bytes(), b"DIMENS"), "DIMENS")
        source_pvtnum = _expand_integers(
            _keyword_payload(regions.read_bytes(), b"PVTNUM"), "PVTNUM"
        )
        if source_dimens != dimens or source_pvtnum != pvtnum:
            continue
        cells = _compdat_cells(schedule, known_wells)
        if cells and {well for well, _, _, _ in cells} == known_wells:
            return cells
    raise SummaryPlanError(
        "COMPDATMD cannot be converted to I/J/K without a trajectory/grid intersection; "
        "point AIOS_COMPDAT_MODEL_DIR at an equivalent COMPDAT revision with "
        "matching DIMENS and PVTNUM"
    )


@dataclass(frozen=True, slots=True)
class RegionPlan:
    source_keyword: str
    report_keyword: str
    values: tuple[int, ...]
    regions: tuple[int, ...]
    dimens: tuple[int, int, int]


def _run_length_encode(values: Iterable[int]) -> tuple[str, ...]:
    tokens: list[str] = []
    current: int | None = None
    count = 0
    for value in values:
        if value == current:
            count += 1
            continue
        if current is not None:
            tokens.append(f"{count}*{current}" if count > 1 else str(current))
        current = value
        count = 1
    if current is not None:
        tokens.append(f"{count}*{current}" if count > 1 else str(current))
    return tuple(tokens)


def build_region_plan(model_dir: Path | str) -> RegionPlan:
    model_dir = Path(model_dir).resolve()
    data_path = model_dir / _MODEL_DATA
    regions_path = model_dir / _REGIONS_INCLUDE
    for path in (data_path, regions_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    dimens = _expand_integers(
        _keyword_payload(data_path.read_bytes(), b"DIMENS"), "DIMENS"
    )
    if len(dimens) != 3:
        raise SummaryPlanError(f"DIMENS: expected 3 values, got {len(dimens)}")
    nx, ny, nz = dimens
    raw_regions = regions_path.read_bytes()
    keyword = REGION_MARKUP_KEYWORD.encode("ascii")
    if not any(line.strip() == keyword for line in raw_regions.splitlines()):
        raise SummaryPlanError(
            f"{_REGIONS_INCLUDE}: no {REGION_MARKUP_KEYWORD} array; "
            f"there is nothing to build the region markup for {REGION_REPORT_KEYWORD} from"
        )
    values = _expand_integers(
        _keyword_payload(raw_regions, keyword), REGION_MARKUP_KEYWORD
    )
    if len(values) != nx * ny * nz:
        raise SummaryPlanError(
            f"{REGION_MARKUP_KEYWORD}: expected {nx * ny * nz} cells, "
            f"got {len(values)}"
        )
    if any(value < 0 for value in values):
        raise SummaryPlanError(
            f"{REGION_MARKUP_KEYWORD}: a negative region number is not allowed"
        )
    regions = tuple(sorted({value for value in values if value > 0}))
    if not regions:
        raise SummaryPlanError(
            f"{REGION_MARKUP_KEYWORD}: all cells are zero, there are no "
            "marked-up regions"
        )
    return RegionPlan(
        source_keyword=REGION_MARKUP_KEYWORD,
        report_keyword=REGION_REPORT_KEYWORD,
        values=values,
        regions=regions,
        dimens=(nx, ny, nz),
    )


def render_region_report_array(plan: RegionPlan) -> bytes:
    tokens = _run_length_encode(plan.values)
    lines = [f"\n{plan.report_keyword}\n"]
    for start in range(0, len(tokens), REGION_VALUES_PER_LINE):
        chunk = tokens[start : start + REGION_VALUES_PER_LINE]
        lines.append(" " + " ".join(chunk) + "\n")
    lines.append("/\n")
    return "".join(lines).encode("ascii")


def render_region_summary_include(plan: RegionPlan) -> bytes:
    lines = [f"\n{REGION_PRESSURE_KEY}\n"]
    lines.extend(f" {region}\n" for region in plan.regions)
    lines.append("/\n")
    return "".join(lines).encode("ascii")


def build_summary_plan(
    model_dir: Path | str,
    wells: Iterable[str],
    spec: SummarySpec | None = None,
) -> SummaryPlan:
    model_dir = Path(model_dir).resolve()
    data_path = model_dir / _MODEL_DATA
    regions_path = model_dir / _REGIONS_INCLUDE
    schedule_path = model_dir / _SCHEDULE_INCLUDE
    for path in (data_path, regions_path, schedule_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    dimens = _expand_integers(_keyword_payload(data_path.read_bytes(), b"DIMENS"), "DIMENS")
    if len(dimens) != 3:
        raise SummaryPlanError(f"DIMENS: expected 3 values, got {len(dimens)}")
    nx, ny, nz = dimens
    pvtnum = _expand_integers(
        _keyword_payload(regions_path.read_bytes(), b"PVTNUM"), "PVTNUM"
    )
    if len(pvtnum) != nx * ny * nz:
        raise SummaryPlanError(
            f"PVTNUM: expected {nx * ny * nz} cells, got {len(pvtnum)}"
        )

    well_axis = tuple(wells)
    if len(well_axis) != len(set(well_axis)) or well_axis != tuple(sorted(well_axis)):
        raise SummaryPlanError("the wells axis must be unique and lexicographic")
    known_wells = set(well_axis)
    parsed = parse_schedule(schedule_path.read_bytes())
    cells = _compdat_cells(schedule_path, known_wells)

    if not cells and any(block.keyword == "COMPDATMD" for block in parsed.blocks):
        cells = _equivalent_compdat_cells(
            model_dir, known_wells, (nx, ny, nz), pvtnum
        )

    cell_wells = {well for well, _, _, _ in cells}
    if cell_wells != known_wells:
        missing = sorted(known_wells - cell_wells)
        extra = sorted(cell_wells - known_wells)
        raise SummaryPlanError(
            f"WELSPECS and COMPDAT axes diverge: without connections={missing}, extra={extra}"
        )

    connections: list[SummaryConnection] = []
    for well, i, j, k in sorted(cells):
        region = pvtnum[_grid_index(i, j, k, nx, ny, nz)]
        if region <= 0:
            raise SummaryPlanError(
                f"COMPDAT {well!r}: cell ({i}, {j}, {k}) is inactive per PVTNUM"
            )
        connections.append(SummaryConnection(well, i, j, k, region))

    region_counts = Counter(connection.pvt_region for connection in connections)
    if set(region_counts) != {1, 2}:
        raise SummaryPlanError(f"Model_Z: expected PVT regions 1 and 2, got {region_counts}")
    return SummaryPlan(
        spec=spec if spec is not None else SummarySpec(),
        wells=well_axis,
        connections=tuple(connections),
    )


def render_summary_include(plan: SummaryPlan) -> bytes:
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
