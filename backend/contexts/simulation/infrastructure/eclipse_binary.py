from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from backend.contexts.simulation.domain.errors import ResponseLoaderError
from backend.contexts.reservoir.infrastructure.summary import _TOKEN_RE

_ELEMENTS_PER_BLOCK = {"INTE": 1000, "REAL": 1000, "DOUB": 1000, "LOGI": 1000, "CHAR": 105}


def _iter_fortran_records(path: Path) -> Iterator[bytes]:
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
                f"{path}: mismatched Fortran record markers at offset {pos}"
            )
        yield payload


def _iter_keyword_arrays(records: Iterator[bytes]) -> Iterator[tuple[str, str, list]]:
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
                raise ResponseLoaderError(f"{keyword!r}: unsupported type {arr_type!r}")
            remaining -= n
        yield keyword, arr_type, values


@dataclass(frozen=True, slots=True)
class _SmSpecIndex:
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
        raise ResponseLoaderError(f"{path}: required SMSPEC keys are missing: {missing}")
    keywords, wgnames, nums, dimens = (
        arrays["KEYWORDS"],
        arrays["WGNAMES"],
        arrays["NUMS"],
        arrays["DIMENS"],
    )
    if not (len(keywords) == len(wgnames) == len(nums)):
        raise ResponseLoaderError(f"{path}: KEYWORDS/WGNAMES/NUMS have differing lengths")
    if len(dimens) < 4:
        raise ResponseLoaderError(f"{path}: DIMENS is shorter than expected")
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
    rows: list[tuple[float, ...]] = []
    current: tuple[float, ...] | None = None
    seen_seqhdr = False
    for keyword, _arr_type, values in _iter_keyword_arrays(_iter_fortran_records(path)):
        if keyword == "SEQHDR":
            if seen_seqhdr:
                if current is None:
                    raise ResponseLoaderError(f"{path}: report step without PARAMS")
                rows.append(current)
                current = None
            seen_seqhdr = True
        elif keyword == "PARAMS":
            if len(values) != n_vectors:
                raise ResponseLoaderError(
                    f"{path}: PARAMS of length {len(values)}, expected {n_vectors}"
                )
            current = tuple(values)
    if not seen_seqhdr:
        raise ResponseLoaderError(f"{path}: no SEQHDR was found")
    if current is None:
        raise ResponseLoaderError(f"{path}: the last report step is without PARAMS")
    rows.append(current)
    return rows


def load_density_by_pvtnum(model_dir: Path | str) -> dict[int, float]:
    props_path = Path(model_dir).resolve() / "Model_Z_props.inc"
    if not props_path.is_file():
        raise FileNotFoundError(props_path)
    lines = props_path.read_bytes().splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == b"DENSITY"]
    if len(starts) != 1:
        raise ResponseLoaderError(f"{props_path}: expected one DENSITY block, found {len(starts)}")
    densities: list[float] = []
    for line in lines[starts[0] + 1 :]:
        if not line.strip():
            break
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue
        if not body.endswith(b"/"):
            raise ResponseLoaderError(f"{props_path}: the DENSITY record is not closed with '/': {body!r}")
        tokens = [
            (match.group(1) if match.group(1) is not None else match.group(2))
            for match in _TOKEN_RE.finditer(body[:-1])
        ]
        if not tokens:
            raise ResponseLoaderError(f"{props_path}: empty DENSITY record")
        densities.append(float(tokens[0].decode("ascii")))
    if not densities:
        raise ResponseLoaderError(f"{props_path}: DENSITY contains no records")
    return {pvtnum: density for pvtnum, density in enumerate(densities, start=1)}

