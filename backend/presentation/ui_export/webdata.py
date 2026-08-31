import json
import os
from pathlib import Path
from typing import Any

from backend.core.paths import project_root
from backend.presentation.ui_export.deck import load_completions, load_wellheads

GRID_NI: int = 91
GRID_NJ: int = 102
GRID_NK: int = 59
DECK_RELATIVE: Path = Path("models") / "Model_Z" / "Model_Z_sch.inc"


def default_deck_path() -> Path:
    from_env = os.environ.get("AIOS_DOCS_ROOT")
    roots = (
        (Path(from_env),)
        if from_env
        else tuple(parent / "docs" for parent in project_root().parents)
    )
    for root in roots:
        candidate = root / DECK_RELATIVE
        if candidate.exists():
            return candidate
    return roots[0] / DECK_RELATIVE


DEFAULT_DECK_PATH: Path = default_deck_path()
DEFAULT_OUT_PATH: Path = project_root() / "frontend" / "public" / "data" / "wells.json"


def _packaged_geometry(heads: dict[str, tuple[int, int]]) -> dict[str, Any] | None:
    """Use the audited cell-index geometry for a COMPDATMD-only deck.

    COMPDATMD contains measured depth, not I/J/K cells; converting it requires
    a trajectory/grid intersection engine and must not be approximated in the
    UI exporter.  The repository ships geometry generated from the equivalent
    cell-index Model Z revision.  It is accepted only when every wellhead id
    and I/J coordinate matches the current deck.
    """

    path = DEFAULT_OUT_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    wells = data.get("wells")
    if not isinstance(wells, list):
        return None
    packaged_heads = {
        str(item.get("id")): (item.get("i"), item.get("j"))
        for item in wells
        if isinstance(item, dict)
    }
    if packaged_heads != heads:
        return None
    return {
        "grid": data["grid"],
        "layers": data["layers"],
        "wells": wells,
    }


def occupied_k_values(completions: dict[str, list[tuple[int, int, int, int]]]) -> list[int]:
    occupied: set[int] = set()
    for intervals in completions.values():
        for _, _, k1, k2 in intervals:
            occupied.update(range(k1, k2 + 1))
    return sorted(occupied)


def split_layers(occupied: list[int]) -> tuple[int, int]:
    if len(occupied) < 2:
        raise ValueError("need at least two occupied K values to split layers")
    best_index = 0
    best_gap = 0
    for index in range(len(occupied) - 1):
        gap = occupied[index + 1] - occupied[index]
        if gap > best_gap:
            best_gap = gap
            best_index = index
    if best_gap <= 1:
        best_index = len(occupied) // 2 - 1
    return occupied[best_index], occupied[best_index + 1]


def build_wells_data(deck_path: str | Path = DEFAULT_DECK_PATH) -> dict[str, Any]:
    heads = load_wellheads(deck_path)
    completions = load_completions(deck_path)
    if not completions:
        packaged = _packaged_geometry(heads)
        if packaged is not None:
            return packaged
        raise ValueError(
            "deck has no cell-index COMPDAT records and no matching audited "
            "packaged geometry; COMPDATMD cannot be converted to K cells without "
            "trajectory/grid intersection"
        )
    occupied = occupied_k_values(completions)
    layer1_max, layer2_min = split_layers(occupied)
    wells: list[dict[str, Any]] = []
    for well in sorted(heads, key=lambda name: (len(name), name)):
        i, j = heads[well]
        intervals = [(k1, k2) for _, _, k1, k2 in completions.get(well, [])]
        layers: list[int] = []
        if any(k1 <= layer1_max for k1, _ in intervals):
            layers.append(1)
        if any(k2 >= layer2_min for _, k2 in intervals):
            layers.append(2)
        wells.append(
            {
                "id": well,
                "i": i,
                "j": j,
                "completions": [[k1, k2] for k1, k2 in intervals],
                "layers": layers,
            }
        )
    return {
        "grid": {"ni": GRID_NI, "nj": GRID_NJ, "nk": GRID_NK},
        "layers": [
            {"id": 1, "k_min": occupied[0], "k_max": layer1_max},
            {"id": 2, "k_min": layer2_min, "k_max": occupied[-1]},
        ],
        "wells": wells,
    }


def export_wells_json(
    deck_path: str | Path = DEFAULT_DECK_PATH, out_path: str | Path = DEFAULT_OUT_PATH
) -> Path:
    data = build_wells_data(deck_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> None:
    out = export_wells_json()
    print(out)


if __name__ == "__main__":
    main()
