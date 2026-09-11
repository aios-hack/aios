from __future__ import annotations

import hashlib
from math import isnan
from pathlib import Path
from typing import Mapping, Sequence

from backend.contexts.simulation.domain.errors import ResponseLoaderError
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate
from backend.contexts.runs.domain.run_result import ResponseArtifact, RunResult, RunStatus
from backend.shared.hashing import canonical_bytes
from backend.contexts.reservoir.infrastructure.summary import SummaryPlan

from backend.contexts.simulation.infrastructure.eclipse_binary import (
    _ELEMENTS_PER_BLOCK,
    _SmSpecIndex,
    _iter_fortran_records,
    _iter_keyword_arrays,
    _read_smspec,
    _read_unsmry_report_rows,
    load_density_by_pvtnum,
)
from backend.contexts.simulation.infrastructure.well_rows import (
    _KG_PER_TONNE,
    _WellRow,
    _build_well_rows,
    _connections_by_well,
)
from backend.contexts.simulation.infrastructure.well_timeline import (
    _ACHIEVEMENT_THRESHOLD,
    _BHP_LIMIT_TOLERANCE_BAR,
    _GROUP_CODE,
    _INJECTOR_BHP_LIMIT_BAR,
    _NO_ACTIVE_CONTROL_CODE,
    _PRESSURE_CODES,
    _PRODUCER_BHP_LIMIT_BAR,
    _RATE_CODES,
    _WellTimeline,
    _build_interval_response,
    _build_state_at_date,
    build_well_timelines,
    _control_step_for_date,
    _fallback_control_mode,
    _resolve_control_mode,
)

__all__ = [
    "ResponseLoader",
    "ResponseLoaderError",
    "load_density_by_pvtnum",
]


_NUMERIC_STATE_FIELDS = ("liquid_rate", "oil_rate", "injection_rate", "thp", "bhp", "well_efficiency")
_NUMERIC_INTERVAL_FIELDS = ("oil_mass_delta", "liquid_volume_delta", "injection_volume_delta")


def _check_no_nan(
    state_at_date: tuple[StateAtDate, ...],
    interval_response: tuple[IntervalResponse, ...],
) -> None:
    for state in state_at_date:
        for field in _NUMERIC_STATE_FIELDS:
            if isnan(getattr(state, field)):
                raise ResponseLoaderError(
                    f"NaN in StateAtDate[{state.deck_date_index}, {state.well}].{field}"
                )
    for interval in interval_response:
        for field in _NUMERIC_INTERVAL_FIELDS:
            if isnan(getattr(interval, field)):
                raise ResponseLoaderError(
                    f"NaN in IntervalResponse[{interval.control_step}, {interval.well}].{field}"
                )


def _find_artifact(paths: Sequence[str], suffix: str) -> Path:
    matches = [Path(path) for path in paths if path.upper().endswith(suffix)]
    if len(matches) != 1:
        raise ResponseLoaderError(
            f"expected exactly one *{suffix} artifact, found {len(matches)}: {matches}"
        )
    return matches[0]


class ResponseLoader:
    def load(
        self,
        run_result: RunResult,
        summary_plan: SummaryPlan,
        schedule: Schedule,
        density_by_pvtnum: Mapping[int, float],
    ) -> ResponseArtifact:
        if run_result.status is not RunStatus.OK:
            raise ResponseLoaderError(
                f"RunResult {run_result.run_id!r} is not OK ({run_result.status}): "
                "an unsuccessful run is not passed off as a valid response"
            )

        smspec_path = _find_artifact(run_result.artifacts, "SMSPEC")
        unsmry_path = _find_artifact(run_result.artifacts, "UNSMRY")

        smspec = _read_smspec(smspec_path)
        report_rows_raw = _read_unsmry_report_rows(unsmry_path, smspec.n_vectors)
        well_rows = _build_well_rows(smspec, report_rows_raw, summary_plan, density_by_pvtnum)

        state_at_date = _build_state_at_date(well_rows, summary_plan.wells, schedule)
        interval_response = _build_interval_response(well_rows, summary_plan.wells)

        _check_no_nan(state_at_date, interval_response)

        response_hash = hashlib.sha256(
            canonical_bytes(
                {"state_at_date": state_at_date, "interval_response": interval_response}
            )
        ).hexdigest()

        return ResponseArtifact(
            source_run_id=run_result.run_id,
            response_hash=response_hash,
            state_at_date=state_at_date,
            interval_response=interval_response,
        )
