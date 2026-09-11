from __future__ import annotations

from backend.contexts.reservoir.application.well_geometry import (
    DECK_RELATIVE,
    DEFAULT_DECK_PATH,
    DEFAULT_OUT_PATH,
    GRID_NI,
    GRID_NJ,
    GRID_NK,
    build_wells_data,
    default_deck_path,
    export_wells_json,
    main,
    occupied_k_values,
    split_layers,
)


if __name__ == "__main__":
    from backend.contexts.reservoir.application.well_geometry import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "DECK_RELATIVE",
    "DEFAULT_DECK_PATH",
    "DEFAULT_OUT_PATH",
    "GRID_NI",
    "GRID_NJ",
    "GRID_NK",
    "build_wells_data",
    "default_deck_path",
    "export_wells_json",
    "main",
    "occupied_k_values",
    "split_layers",
]
