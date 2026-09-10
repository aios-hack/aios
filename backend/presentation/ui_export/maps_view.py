from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from backend.core.paths import project_root

GRID_NI: int = 91
GRID_NJ: int = 102
GRID_NK: int = 59

GRID_RELATIVE: Path = Path("models") / "Model_Z" / "Model_Z_grid.inc"
REGS_RELATIVE: Path = Path("models") / "Model_Z" / "Model_Z_regs.inc"

NODATA: int = 255
QUANT_MAX: int = 254

LINEAR: str = "linear"
LOG: str = "log"
CATEGORICAL: str = "categorical"

PROP_SCALES: dict[str, str] = {
    "PORO": LINEAR,
    "NTG": LINEAR,
    "PERMX": LOG,
    "TOP": LINEAR,
    "FIP_ZONE": CATEGORICAL,
    "EQLNUM": CATEGORICAL,
}

GRID_PROPS: tuple[str, ...] = ("ACTNUM", "PORO", "NTG", "PERMX")
REGS_PROPS: tuple[str, ...] = ("FIP_ZONE", "EQLNUM")

_KEYWORD_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _docs_roots() -> tuple[Path, ...]:
    from_env = os.environ.get("AIOS_DOCS_ROOT")
    if from_env:
        return (Path(from_env),)
    return tuple(parent / "docs" for parent in project_root().parents)


def _deck_file(relative: Path) -> Path:
    roots = _docs_roots()
    for root in roots:
        candidate = root / relative
        if candidate.exists():
            return candidate
    return roots[0] / relative


def default_grid_path() -> Path:
    return _deck_file(GRID_RELATIVE)


def default_regs_path() -> Path:
    return _deck_file(REGS_RELATIVE)


DEFAULT_OUT_DIR: Path = project_root() / "frontend" / "public" / "data" / "maps"


def _is_keyword(line: str) -> bool:
    if not line or line[0] not in _KEYWORD_CHARS or line[0].isdigit():
        return False
    return all(char in _KEYWORD_CHARS for char in line)


def _iter_values(path: Path, keyword: str) -> Iterator[float]:
    active = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.split("--", 1)[0].strip()
            if not line:
                continue
            if not active:
                if line.upper() == keyword:
                    active = True
                continue
            if line == "/":
                return
            if _is_keyword(line):
                return
            body = line.rstrip("/").strip()
            if not body:
                return
            for token in body.split():
                if "*" in token:
                    count, _, value = token.partition("*")
                    yield from (float(value),) * int(count)
                else:
                    yield float(token)
            if line.endswith("/"):
                return


def read_values(path: str | Path, keyword: str, expected: int | None = None) -> np.ndarray:
    values = np.fromiter(_iter_values(Path(path), keyword), dtype=np.float64)
    if values.size == 0:
        raise ValueError(f"{keyword} not found in {path}")
    if expected is not None and values.size != expected:
        raise ValueError(
            f"{keyword} in {path}: expected {expected} values, read {values.size}"
        )
    return values


def cell_centres(
    coord: np.ndarray, ni: int = GRID_NI, nj: int = GRID_NJ
) -> tuple[np.ndarray, np.ndarray]:
    pillars = coord.reshape((nj + 1, ni + 1, 6))
    top_x = pillars[:, :, 0]
    top_y = pillars[:, :, 1]
    xs = 0.25 * (
        top_x[:-1, :-1] + top_x[:-1, 1:] + top_x[1:, :-1] + top_x[1:, 1:]
    )
    ys = 0.25 * (
        top_y[:-1, :-1] + top_y[:-1, 1:] + top_y[1:, :-1] + top_y[1:, 1:]
    )
    return xs, ys


def layer_tops(
    zcorn: np.ndarray, ni: int = GRID_NI, nj: int = GRID_NJ, nk: int = GRID_NK
) -> np.ndarray:
    corners = zcorn.reshape((nk, 2, nj, 2, ni, 2))
    return corners[:, 0].mean(axis=(2, 4))


def quantise(
    values: np.ndarray, active: np.ndarray, scale: str
) -> tuple[list[int], float, float]:
    live = values[active]
    if live.size == 0:
        return [NODATA] * int(values.size), 0.0, 0.0
    if scale == LOG:
        floor = live[live > 0.0]
        base = float(floor.min()) if floor.size else 1e-6
        prepared = np.log10(np.maximum(values, base))
        low = float(np.log10(base))
        high = float(prepared[active].max())
    else:
        prepared = values
        low = float(live.min())
        high = float(live.max())
    span = high - low
    if span <= 0.0:
        codes = np.zeros(values.shape, dtype=np.int64)
    else:
        normalised = (prepared - low) / span
        codes = np.rint(np.clip(normalised, 0.0, 1.0) * QUANT_MAX).astype(np.int64)
    codes = np.where(active, codes, NODATA)
    flat: list[int] = codes.reshape(-1).tolist()
    if scale == LOG:
        return flat, float(10.0**low), float(10.0**high)
    return flat, low, high


def categorical_codes(
    values: np.ndarray, active: np.ndarray
) -> tuple[list[int], float, float]:
    codes = np.where(active, np.rint(values).astype(np.int64), NODATA)
    flat: list[int] = codes.reshape(-1).tolist()
    live = values[active]
    if live.size == 0:
        return flat, 0.0, 0.0
    return flat, float(live.min()), float(live.max())


class DeckGrid:
    def __init__(
        self,
        grid_path: str | Path | None = None,
        regs_path: str | Path | None = None,
        ni: int = GRID_NI,
        nj: int = GRID_NJ,
        nk: int = GRID_NK,
    ) -> None:
        self.ni = ni
        self.nj = nj
        self.nk = nk
        self.grid_path = Path(grid_path) if grid_path is not None else default_grid_path()
        self.regs_path = Path(regs_path) if regs_path is not None else default_regs_path()
        self._cache: dict[str, np.ndarray] = {}

    @property
    def cells(self) -> int:
        return self.ni * self.nj * self.nk

    def _source(self, prop: str) -> Path:
        return self.regs_path if prop in REGS_PROPS else self.grid_path

    def cube(self, prop: str) -> np.ndarray:
        cached = self._cache.get(prop)
        if cached is not None:
            return cached
        if prop == "TOP":
            zcorn = read_values(self.grid_path, "ZCORN", self.cells * 8)
            cube = layer_tops(zcorn, self.ni, self.nj, self.nk)
        else:
            flat = read_values(self._source(prop), prop, self.cells)
            cube = flat.reshape((self.nk, self.nj, self.ni))
        self._cache[prop] = cube
        return cube

    def bounds(self) -> dict[str, float]:
        coord = read_values(self.grid_path, "COORD", (self.ni + 1) * (self.nj + 1) * 6)
        xs, ys = cell_centres(coord, self.ni, self.nj)
        return {
            "xmin": float(xs.min()),
            "xmax": float(xs.max()),
            "ymin": float(ys.min()),
            "ymax": float(ys.max()),
        }

    def layer(self, prop: str, k: int) -> dict[str, Any]:
        actnum = self.cube("ACTNUM")[k]
        active = actnum > 0.5
        values = self.cube(prop)[k]
        scale = PROP_SCALES[prop]
        if scale == CATEGORICAL:
            codes, low, high = categorical_codes(values, active)
        else:
            codes, low, high = quantise(values, active, scale)
        return {
            "k": k + 1,
            "prop": prop,
            "min": low,
            "max": high,
            "nodata": NODATA,
            "q": codes,
        }


def load_wells(wells_path: str | Path) -> list[dict[str, Any]]:
    path = Path(wells_path)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("wells")
    if not isinstance(rows, list):
        return []
    wells: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        completions = row.get("completions") or []
        ks = [int(k) for pair in completions for k in pair]
        wells.append(
            {
                "id": str(row["id"]),
                "i": int(row["i"]) - 1,
                "j": int(row["j"]) - 1,
                "k_from": min(ks) if ks else None,
                "k_to": max(ks) if ks else None,
                "layers": row.get("layers", []),
            }
        )
    return wells


def build_index(
    grid: DeckGrid,
    wells: list[dict[str, Any]],
    props: tuple[str, ...],
) -> dict[str, Any]:
    layer_ranges = [
        {"id": 1, "k_min": 1, "k_max": 26},
        {"id": 2, "k_min": 29, "k_max": 53},
    ]
    group_of: dict[int, int | None] = {}
    for k in range(1, grid.nk + 1):
        group = None
        for entry in layer_ranges:
            if entry["k_min"] <= k <= entry["k_max"]:
                group = entry["id"]
                break
        group_of[k] = group
    return {
        "ni": grid.ni,
        "nj": grid.nj,
        "nk": grid.nk,
        "bounds": grid.bounds(),
        "groups": layer_ranges,
        "layers": [{"k": k, "group": group_of[k]} for k in range(1, grid.nk + 1)],
        "props": [{"id": prop, "scale": PROP_SCALES[prop]} for prop in props],
        "wells": wells,
        "provenance": "Model_Z deck, static properties",
    }


EXPORT_PROPS: tuple[str, ...] = ("PORO", "PERMX", "NTG", "TOP", "FIP_ZONE", "EQLNUM")


def export_maps(
    out_dir: str | Path = DEFAULT_OUT_DIR,
    grid_path: str | Path | None = None,
    regs_path: str | Path | None = None,
    props: tuple[str, ...] = EXPORT_PROPS,
    wells_path: str | Path | None = None,
) -> Path:
    grid = DeckGrid(grid_path, regs_path)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    for prop in props:
        prop_dir = root / prop
        prop_dir.mkdir(parents=True, exist_ok=True)
        for k in range(grid.nk):
            payload = grid.layer(prop, k)
            (prop_dir / f"{k + 1}.json").write_text(
                json.dumps(payload, separators=(",", ":")), encoding="utf-8"
            )
    default_wells = project_root() / "frontend" / "public" / "data" / "wells.json"
    wells = load_wells(wells_path if wells_path is not None else default_wells)
    index = build_index(grid, wells, props)
    index_path = root / "index.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return index_path


def main() -> None:
    print(export_maps())


if __name__ == "__main__":
    main()
