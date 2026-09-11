from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.core.contracts import ActiveControlMode, IntervalResponse, StateAtDate


@dataclass(frozen=True)
class ExampleInput:
    states_by_well: dict[str, list[StateAtDate]]
    responses_by_well: dict[str, list[IntervalResponse]]
    interval_start_dates: list[date]
    records: list[dict[str, Any]]

    @property
    def start_year(self) -> int:
        return self.interval_start_dates[0].year

    @property
    def n_wells(self) -> int:
        return len(self.states_by_well)

    @property
    def n_intervals(self) -> int:
        return len(self.interval_start_dates)


def load_example_input(chdd_python_dir: Path, source_xlsx: Path) -> ExampleInput:
    if str(chdd_python_dir) not in sys.path:
        sys.path.insert(0, str(chdd_python_dir))
    from excel_io import load_source_records

    _, records = load_source_records(source_xlsx)
    rows_by_well: dict[str, list[tuple[date, dict[str, Any]]]] = {}
    for record in records:
        raw = record["DATA"]
        moment = raw.date() if isinstance(raw, datetime) else raw
        rows_by_well.setdefault(str(record["well"]), []).append((moment, record))
    for rows in rows_by_well.values():
        rows.sort(key=lambda item: item[0])

    deck_dates = sorted({moment for rows in rows_by_well.values() for moment, _ in rows})
    n_intervals = len(deck_dates) - 1
    interval_start_dates = deck_dates[1:]

    states_by_well: dict[str, list[StateAtDate]] = {}
    responses_by_well: dict[str, list[IntervalResponse]] = {}
    for well, rows in rows_by_well.items():
        row_by_date = {moment: record for moment, record in rows}
        states_by_well[well] = [
            StateAtDate(
                deck_date_index=index,
                well=well,
                liquid_rate=float(row_by_date[moment]["WLPR"]),
                oil_rate=float(row_by_date[moment]["WOMR"]),
                injection_rate=float(row_by_date[moment]["WWIR"]),
                thp=float(row_by_date[moment]["THP"]),
                bhp=float(row_by_date[moment]["BHP"]),
                well_efficiency=float(row_by_date[moment]["WEFF"]),
                active_control_mode=ActiveControlMode.UNKNOWN,
            )
            for index, moment in enumerate(deck_dates)
        ]
        responses_by_well[well] = [
            IntervalResponse(
                control_step=control_step,
                well=well,
                oil_mass_delta=float(
                    row_by_date[deck_dates[control_step + 1]]["WOMT_Diff"]
                ),
                liquid_volume_delta=float(
                    row_by_date[deck_dates[control_step + 1]]["WLPT_Diff"]
                ),
                injection_volume_delta=float(
                    row_by_date[deck_dates[control_step + 1]]["WWIT_Diff"]
                ),
            )
            for control_step in range(n_intervals)
        ]

    return ExampleInput(
        states_by_well=states_by_well,
        responses_by_well=responses_by_well,
        interval_start_dates=interval_start_dates,
        records=list(records),
    )
