import json
from pathlib import Path
from typing import Any

from ui.deck import load_completions, load_wellheads

GRID_NI: int = 91
GRID_NJ: int = 102
GRID_NK: int = 59
DEFAULT_DECK_PATH: Path = Path(__file__).resolve().parents[2] / "docs" / "models" / "Model_Z" / "Model_Z_sch.inc"
DEFAULT_OUT_PATH: Path = Path(__file__).resolve().parent / "web" / "public" / "data" / "wells.json"


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
