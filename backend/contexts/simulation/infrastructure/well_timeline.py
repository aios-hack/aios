from __future__ import annotations

from typing import Mapping, Sequence

from backend.contexts.simulation.domain.errors import ResponseLoaderError
from backend.contexts.simulation.domain.well_timeline import _WellTimeline, build_well_timelines
from backend.contexts.reservoir.domain.response import (
    ActiveControlMode,
    IntervalResponse,
    N_DECK_DATES,
    StateAtDate,
)
from backend.contexts.schedule.domain.schedule import N_INTERVALS, OperatingStatus, Schedule
from backend.contexts.simulation.infrastructure.well_rows import _WellRow

__all__ = [
    "_ACHIEVEMENT_THRESHOLD",
    "_BHP_LIMIT_TOLERANCE_BAR",
    "_GROUP_CODE",
    "_INJECTOR_BHP_LIMIT_BAR",
    "_NO_ACTIVE_CONTROL_CODE",
    "_PRESSURE_CODES",
    "_PRODUCER_BHP_LIMIT_BAR",
    "_RATE_CODES",
    "_WellTimeline",
    "_build_interval_response",
    "_build_state_at_date",
    "_control_step_for_date",
    "_fallback_control_mode",
    "_resolve_control_mode",
    "build_well_timelines",
]

_RATE_CODES = frozenset({1, 2, 3, 4, 5, 9})
_PRESSURE_CODES = frozenset({6, 7})
_GROUP_CODE = -1
_NO_ACTIVE_CONTROL_CODE = 0

_ACHIEVEMENT_THRESHOLD = 0.999
_PRODUCER_BHP_LIMIT_BAR = 50.0
_INJECTOR_BHP_LIMIT_BAR = 300.0
_BHP_LIMIT_TOLERANCE_BAR = 5.0


def _control_step_for_date(deck_date_index: int) -> int | None:
    if deck_date_index < N_DECK_DATES - N_INTERVALS - 1:
        return None
    return deck_date_index - (N_DECK_DATES - N_INTERVALS)


def _fallback_control_mode(
    *,
    commissioned: bool,
    operating_status: OperatingStatus,
    setpoint: float,
    liquid_rate: float,
    injection_rate: float,
    bhp: float,
) -> ActiveControlMode:
    if not commissioned:
        return ActiveControlMode.NOT_COMMISSIONED
    if operating_status is OperatingStatus.SHUT:
        return ActiveControlMode.SHUT
    if setpoint <= 0:
        return ActiveControlMode.UNKNOWN
    is_injector = injection_rate > 0
    actual = injection_rate if is_injector else liquid_rate
    ratio = actual / setpoint
    limit = _INJECTOR_BHP_LIMIT_BAR if is_injector else _PRODUCER_BHP_LIMIT_BAR
    near_limit = abs(bhp - limit) <= _BHP_LIMIT_TOLERANCE_BAR
    if ratio < _ACHIEVEMENT_THRESHOLD and near_limit:
        return ActiveControlMode.BHP_LIMITED
    return ActiveControlMode.RATE_TARGET


def _resolve_control_mode(
    well: str,
    deck_date_index: int,
    well_row: _WellRow,
    timelines: Mapping[str, _WellTimeline],
) -> ActiveControlMode:
    control_step = _control_step_for_date(deck_date_index)
    timeline = timelines.get(well)
    commissioned = (
        True if control_step is None or timeline is None else timeline.is_commissioned(control_step)
    )

    if well_row.wmctl is not None:
        code = round(well_row.wmctl)
        if code in _RATE_CODES or code == _GROUP_CODE:
            return ActiveControlMode.RATE_TARGET
        if code in _PRESSURE_CODES:
            return ActiveControlMode.BHP_LIMITED
        if code == _NO_ACTIVE_CONTROL_CODE:
            return ActiveControlMode.SHUT if commissioned else ActiveControlMode.NOT_COMMISSIONED
        return ActiveControlMode.UNKNOWN

    if control_step is None or timeline is None:
        return ActiveControlMode.UNKNOWN
    return _fallback_control_mode(
        commissioned=commissioned,
        operating_status=timeline.operating_status(control_step),
        setpoint=timeline.setpoint(control_step),
        liquid_rate=well_row.liquid_rate,
        injection_rate=well_row.injection_rate,
        bhp=well_row.bhp,
    )


def _build_state_at_date(
    report_rows: list[dict[str, _WellRow]],
    wells: Sequence[str],
    schedule: Schedule,
) -> tuple[StateAtDate, ...]:
    if len(report_rows) != N_DECK_DATES:
        raise ResponseLoaderError(
            f"UNSMRY yields {len(report_rows)} report step(s), the contract requires {N_DECK_DATES}"
        )
    timelines = build_well_timelines(schedule)
    result: list[StateAtDate] = []
    for well in wells:
        for deck_date_index in range(N_DECK_DATES):
            well_row = report_rows[deck_date_index][well]
            mode = _resolve_control_mode(well, deck_date_index, well_row, timelines)
            result.append(
                StateAtDate(
                    deck_date_index=deck_date_index,
                    well=well,
                    liquid_rate=well_row.liquid_rate,
                    oil_rate=well_row.oil_rate,
                    injection_rate=well_row.injection_rate,
                    thp=well_row.thp,
                    bhp=well_row.bhp,
                    well_efficiency=well_row.well_efficiency,
                    active_control_mode=mode,
                )
            )
    return tuple(result)


def _build_interval_response(
    report_rows: list[dict[str, _WellRow]],
    wells: Sequence[str],
) -> tuple[IntervalResponse, ...]:
    if len(report_rows) != N_DECK_DATES:
        raise ResponseLoaderError(
            f"UNSMRY yields {len(report_rows)} report step(s), the contract requires {N_DECK_DATES}"
        )
    result: list[IntervalResponse] = []
    for well in wells:
        oil_mass_cum = [report_rows[d][well].oil_mass_cum for d in range(N_DECK_DATES)]
        liquid_cum = [report_rows[d][well].liquid_cum for d in range(N_DECK_DATES)]
        injection_cum = [report_rows[d][well].injection_cum for d in range(N_DECK_DATES)]
        oil_mass_diff = [oil_mass_cum[i + 1] - oil_mass_cum[i] for i in range(N_DECK_DATES - 1)]
        liquid_diff = [liquid_cum[i + 1] - liquid_cum[i] for i in range(N_DECK_DATES - 1)]
        injection_diff = [injection_cum[i + 1] - injection_cum[i] for i in range(N_DECK_DATES - 1)]
        for k in range(N_INTERVALS):
            i = N_DECK_DATES - N_INTERVALS - 1 + k
            result.append(
                IntervalResponse(
                    control_step=k,
                    well=well,
                    oil_mass_delta=oil_mass_diff[i],
                    liquid_volume_delta=liquid_diff[i],
                    injection_volume_delta=injection_diff[i],
                )
            )
    return tuple(result)
