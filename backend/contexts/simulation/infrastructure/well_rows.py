from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from backend.contexts.simulation.domain.errors import ResponseLoaderError
from backend.contexts.reservoir.infrastructure.summary import SummaryPlan, _grid_index
from backend.contexts.simulation.infrastructure.eclipse_binary import _SmSpecIndex

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
        raise ResponseLoaderError(f"no density for PVTNUM {sorted(missing_density)}")

    well_columns: dict[str, dict[str, int | None]] = {}
    for well in summary_plan.wells:
        columns = {
            key: smspec.column.get((key, well, 0))
            for key in ("WLPR", "WWIR", "WBHP", "WTHP", "WEFF", "WLPT", "WWIT", "WMCTL")
        }
        for key, column in columns.items():
            if column is None and key != "WMCTL":
                raise ResponseLoaderError(f"{well}: vector {key} is missing from SMSPEC")
        well_columns[well] = columns

    connection_columns: dict[str, list[tuple[int, int, float]]] = {}
    for well, connections in connections_by_well.items():
        entries: list[tuple[int, int, float]] = []
        for connection in connections:
            nums = _grid_index(connection.i, connection.j, connection.k, smspec.nx, smspec.ny, smspec.nz) + 1
            copt_column = smspec.column.get(("COPT", well, nums))
            copr_column = smspec.column.get(("COPR", well, nums))
            if copt_column is None or copr_column is None:
                raise ResponseLoaderError(
                    f"{well}: connection ({connection.i},{connection.j},{connection.k}) "
                    "was not found in COPT/COPR by (well, NUMS)"
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

