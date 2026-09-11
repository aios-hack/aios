from __future__ import annotations

from backend.contexts.showcase.application.exporters.maps_view import (
    CATEGORICAL,
    DEFAULT_OUT_DIR,
    DeckGrid,
    EXPORT_PROPS,
    GRID_NI,
    GRID_NJ,
    GRID_NK,
    GRID_PROPS,
    GRID_RELATIVE,
    LINEAR,
    LOG,
    NODATA,
    PROP_SCALES,
    QUANT_MAX,
    REGS_PROPS,
    REGS_RELATIVE,
    build_index,
    categorical_codes,
    cell_centres,
    default_grid_path,
    default_regs_path,
    export_maps,
    layer_tops,
    load_wells,
    main,
    quantise,
    read_values,
)


if __name__ == "__main__":
    from backend.contexts.showcase.application.exporters.maps_view import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "CATEGORICAL",
    "DEFAULT_OUT_DIR",
    "DeckGrid",
    "EXPORT_PROPS",
    "GRID_NI",
    "GRID_NJ",
    "GRID_NK",
    "GRID_PROPS",
    "GRID_RELATIVE",
    "LINEAR",
    "LOG",
    "NODATA",
    "PROP_SCALES",
    "QUANT_MAX",
    "REGS_PROPS",
    "REGS_RELATIVE",
    "build_index",
    "categorical_codes",
    "cell_centres",
    "default_grid_path",
    "default_regs_path",
    "export_maps",
    "layer_tops",
    "load_wells",
    "main",
    "quantise",
    "read_values",
]
