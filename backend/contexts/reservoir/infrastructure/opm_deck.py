from __future__ import annotations

import shutil
from pathlib import Path

from backend.contexts.reservoir.domain.errors import OpmDeckError
from backend.contexts.schedule.domain.schedule import (
    N_CONTROL_DATES,
    N_INTERVALS,
    Schedule,
    T0,
)
from backend.contexts.runs.domain.run_result import SummarySpec
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.reservoir.infrastructure.summary import (
    RegionPlan,
    SummaryPlan,
    SummaryPlanError,
    build_region_plan,
    build_summary_plan,
    render_region_report_array,
    render_region_summary_include,
    render_summary_include,
)
from backend.contexts.reservoir.infrastructure.opm_deck_files import (
    DIAGNOSTIC_DECK_BANNER,
    DIAGNOSTIC_MARKER_NAME,
    DIAGNOSTIC_MARKER_TEXT,
    EmittedOpmDeck,
    EmittedSchedule,
    _INPUT_SUFFIXES,
    _MODEL_DATA,
    _OPM_UNSUPPORTED_GRID_KEYWORDS,
    _REGIONS_INCLUDE,
    _SCHEDULE_INCLUDE,
    _SUMMARY_INCLUDE,
    _UTF8_BOM,
    _block_records,
    _raw_keyword_block,
    _resolve_opm_schedule_template,
    _strip_keyword_records,
    bundle_hash,
)
from backend.contexts.reservoir.infrastructure.opm_deck_render import (
    render_control_period_include,
    render_schedule_include,
    render_submission_history,
)

__all__ = [
    "DIAGNOSTIC_DECK_BANNER",
    "DIAGNOSTIC_MARKER_NAME",
    "DIAGNOSTIC_MARKER_TEXT",
    "EmittedOpmDeck",
    "EmittedSchedule",
    "OpmDeckEmitter",
    "OpmDeckError",
    "RegionPlan",
    "SummaryPlan",
    "SummaryPlanError",
    "build_region_plan",
    "build_summary_plan",
    "bundle_hash",
    "render_control_period_include",
    "render_region_report_array",
    "render_region_summary_include",
    "render_schedule_include",
    "render_submission_history",
    "render_summary_include",
]


class OpmDeckEmitter:
    def __init__(self, model_dir: Path | str) -> None:
        self.model_dir = Path(model_dir).resolve()
        self._data_file = self.model_dir / _MODEL_DATA
        self._schedule_file = self.model_dir / _SCHEDULE_INCLUDE
        if not self._data_file.is_file() or not self._schedule_file.is_file():
            raise FileNotFoundError(
                f"{self.model_dir} must contain {_MODEL_DATA} and {_SCHEDULE_INCLUDE}"
            )
        self._source_schedule_bytes = self._schedule_file.read_bytes()
        self._parsed = parse_schedule(self._source_schedule_bytes)
        self._opm_parsed, self.opm_schedule_source = _resolve_opm_schedule_template(
            self.model_dir, self._source_schedule_bytes, self._parsed
        )
        welspecs = _raw_keyword_block(self._source_schedule_bytes, b"WELSPECS")
        self.source_wells = tuple(sorted(record[0] for record in _block_records(welspecs)))
        if len(self.source_wells) != 103 or len(set(self.source_wells)) != 103:
            raise OpmDeckError(
                f"Model_Z WELSPECS: expected 103 unique wells, "
                f"got {len(set(self.source_wells))}"
            )

    def _validate(self, schedule: Schedule) -> None:
        from backend.contexts.reservoir.domain.horizon import HORIZON
        if len(self._parsed.dates) != HORIZON.n_deck_dates or self._parsed.t0_deck_date_index != HORIZON.history_offset:
            raise OpmDeckError("the full deck dates do not match AIOS_HORIZON_PATH")
        meta = schedule.meta
        if meta.model != "Model_Z" or meta.t0 != T0:
            raise OpmDeckError(f"expected Model_Z with t0={T0}")
        if meta.n_control_dates != N_CONTROL_DATES or meta.n_intervals != N_INTERVALS:
            raise OpmDeckError(
                f"expected {N_CONTROL_DATES} dates and {N_INTERVALS} intervals"
            )
        if tuple(meta.wells) != self.source_wells:
            raise OpmDeckError(
                "the Schedule.meta.wells axis must contain the same 103 WELSPECS "
                "wells in lexicographic order"
            )
        if tuple(schedule.fixed_deck_events) != self._parsed.fixed_deck_events:
            raise OpmDeckError("the fixed layer of Schedule differs from Model_Z")
        unknown = {event.well for event in schedule.control_events} - set(self.source_wells)
        if unknown:
            raise OpmDeckError(f"the control layer addresses unknown wells: {sorted(unknown)}")
        steps = {event.control_step for event in schedule.control_events}
        missing = set(range(N_INTERVALS)) - steps
        if missing:
            raise OpmDeckError(
                f"the control layer is not materialized on all 224 dates; "
                f"steps {sorted(missing)} are missing"
            )

    def emit(
        self,
        schedule: Schedule,
        destination: Path | str,
        *,
        summary_spec: SummarySpec | None = None,
        diagnostic_regions: bool = False,
    ) -> EmittedOpmDeck:
        self._validate(schedule)
        region_plan = (
            build_region_plan(self.model_dir) if diagnostic_regions else None
        )
        destination = Path(destination).resolve()
        if destination == self.model_dir or self.model_dir in destination.parents:
            raise OpmDeckError("destination cannot be the source Model_Z or lie inside it")
        if destination.exists() and any(destination.iterdir()):
            raise FileExistsError(f"destination is not empty: {destination}")
        destination.mkdir(parents=True, exist_ok=True)

        source_files = tuple(
            sorted(
                path
                for path in self.model_dir.iterdir()
                if path.is_file() and path.suffix.lower() in _INPUT_SUFFIXES
            )
        )
        for source in source_files:
            target = destination / source.name
            source_raw = source.read_bytes()
            opm_raw = source_raw.removeprefix(_UTF8_BOM)
            if source.name == "Model_Z_grid.inc":
                target.write_bytes(
                    _strip_keyword_records(
                        opm_raw, _OPM_UNSUPPORTED_GRID_KEYWORDS
                    )
                )
            elif region_plan is not None and source.name == _REGIONS_INCLUDE:
                target.write_bytes(
                    opm_raw
                    + DIAGNOSTIC_DECK_BANNER.encode("ascii")
                    + render_region_report_array(region_plan)
                )
            elif region_plan is not None and source.name == _MODEL_DATA:
                target.write_bytes(
                    DIAGNOSTIC_DECK_BANNER.encode("ascii") + opm_raw
                )
            elif opm_raw != source_raw:
                target.write_bytes(opm_raw)
            else:
                shutil.copy2(source, target)

        emitted_schedule = destination / _SCHEDULE_INCLUDE
        emitted_schedule.write_bytes(
            render_schedule_include(schedule, self.model_dir).raw
        )
        summary_plan = build_summary_plan(
            self.model_dir,
            self.source_wells,
            spec=summary_spec,
        )
        emitted_summary = destination / _SUMMARY_INCLUDE
        summary_bytes = render_summary_include(summary_plan)
        if region_plan is not None:
            summary_bytes = (
                DIAGNOSTIC_DECK_BANNER.encode("ascii")
                + summary_bytes
                + render_region_summary_include(region_plan)
            )
        emitted_summary.write_bytes(summary_bytes)
        marker_file: Path | None = None
        if region_plan is not None:
            marker_file = destination / DIAGNOSTIC_MARKER_NAME
            marker_file.write_text(DIAGNOSTIC_MARKER_TEXT, encoding="utf-8")
        output_files = tuple(
            sorted(
                path
                for path in destination.iterdir()
                if path.is_file() and path.suffix.lower() in _INPUT_SUFFIXES
            )
        )
        return EmittedOpmDeck(
            data_file=destination / _MODEL_DATA,
            schedule_file=emitted_schedule,
            summary_file=emitted_summary,
            summary_plan=summary_plan,
            input_files=output_files,
            content_hash_opm=bundle_hash(output_files, destination),
            diagnostic=region_plan is not None,
            region_plan=region_plan,
            regions_file=(
                destination / _REGIONS_INCLUDE if region_plan is not None else None
            ),
            diagnostic_marker_file=marker_file,
        )
