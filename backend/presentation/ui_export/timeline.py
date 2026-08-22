from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backend.core.contracts import (
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    IntervalResponse,
    RunArtifact,
    Schedule,
    StateAtDate,
    watercut,
)


def _step_date(t0: date, control_step: int) -> str:
    months = t0.month - 1 + control_step
    return date(t0.year + months // 12, months % 12 + 1, t0.day).isoformat()


def _initial_fold(schedule: Schedule) -> dict[str, dict[str, Any]]:
    return {
        well: {
            "availability": state.availability.name,
            "role": state.role.name,
            "operating_status": state.operating_status.name,
            "setpoint": state.setpoint,
        }
        for well, state in schedule.initial_state.items()
    }


def _apply_control(state: dict[str, Any], event: ControlEvent) -> None:
    if event.kind is EventKind.OPEN:
        state["availability"] = "AVAILABLE"
        state["operating_status"] = "OPEN"
    elif event.kind is EventKind.SHUT:
        state["operating_status"] = "SHUT"
    elif event.kind is EventKind.SET_LRAT:
        state["availability"] = "AVAILABLE"
        state["role"] = "PROD"
        state["operating_status"] = "OPEN"
        state["setpoint"] = event.value
    elif event.kind is EventKind.SET_RATE:
        state["availability"] = "AVAILABLE"
        state["role"] = "INJ"
        state["operating_status"] = "OPEN"
        state["setpoint"] = event.value
    elif event.kind is EventKind.CONVERT_INJ:
        state["role"] = "INJ"
        state["setpoint"] = 0.0


def _fact_to_target(state: dict[str, Any], row: StateAtDate) -> float | None:
    if state["availability"] != "AVAILABLE":
        return None
    if state["operating_status"] != "OPEN":
        return None
    setpoint = float(state["setpoint"])
    if setpoint <= 0:
        return None
    fact = row.injection_rate if state["role"] == "INJ" else row.liquid_rate
    return fact / setpoint


def _interval_watercut(
    response: IntervalResponse, densities: dict[str, float]
) -> float:
    if response.liquid_volume_delta <= 0:
        return 0.0
    return watercut(response, densities[response.well] / 1000.0)


_JSON_DIGITS = 6

# Коридор нормы компенсации — параметр политики R5, а не наблюдаемая
# величина: интерфейс рисует по нему полосу на главном графике (F6) и не
# выводит границы из ряда. Поля нет — полосы нет.
COMPENSATION_NORM_MIN = 0.95
COMPENSATION_NORM_MAX = 1.15


def _rounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        rounded = round(value, _JSON_DIGITS)
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


def build_timeline(artifact: RunArtifact, densities: dict[str, float]) -> dict[str, Any]:
    schedule = artifact.schedule
    meta = schedule.meta
    wells = list(meta.wells)
    n_control_dates = meta.n_control_dates
    terminal_step = n_control_dates - 1
    deck_axis = {row.deck_date_index for row in artifact.state_at_date}
    offset = len(deck_axis) - n_control_dates
    state_rows = {
        (row.deck_date_index, row.well): row for row in artifact.state_at_date
    }
    responses = {
        (row.control_step, row.well): row for row in artifact.interval_response
    }
    fixed_by_step: dict[int, list[FixedDeckEvent]] = {}
    for fixed in schedule.fixed_deck_events:
        fixed_by_step.setdefault(fixed.control_step, []).append(fixed)
    control_by_step: dict[int, list[ControlEvent]] = {}
    for event in schedule.control_events:
        control_by_step.setdefault(event.control_step, []).append(event)
    fold = _initial_fold(schedule)
    cumulative = {well: 0.0 for well in wells}
    by_month = artifact.npv_table.by_month
    npv_cumulative = 0.0
    steps: list[dict[str, Any]] = []
    for control_step in range(n_control_dates):
        for fixed in fixed_by_step.get(control_step, []):
            fold[fixed.well]["availability"] = "AVAILABLE"
        for event in control_by_step.get(control_step, []):
            _apply_control(fold[event.well], event)
        terminal = control_step == terminal_step
        state_index = offset + control_step if terminal else offset + 1 + control_step
        if control_step in by_month:
            npv_cumulative += by_month[control_step].discounted_fcf
        production = 0.0
        injection = 0.0
        active_wells = 0
        well_rows: list[dict[str, Any]] = []
        for well in wells:
            row = state_rows[(state_index, well)]
            if row.liquid_rate > 0 or row.injection_rate > 0:
                active_wells += 1
            entry: dict[str, Any] = dict(fold[well])
            entry["well"] = well
            entry["liquid_rate"] = row.liquid_rate
            entry["injection_rate"] = row.injection_rate
            entry["bhp"] = row.bhp
            entry["fact_to_target"] = _fact_to_target(fold[well], row)
            if terminal:
                entry["watercut"] = None
            else:
                response = responses[(control_step, well)]
                production += response.liquid_volume_delta
                injection += response.injection_volume_delta
                cumulative[well] += response.liquid_volume_delta
                entry["watercut"] = _interval_watercut(response, densities)
            entry["cumulative_liquid"] = cumulative[well]
            well_rows.append(entry)
        compensation = injection / production if production > 0 else None
        steps.append(
            {
                "control_step": control_step,
                "date": _step_date(meta.t0, control_step),
                "terminal": terminal,
                "field": {
                    "production": None if terminal else production,
                    "injection": None if terminal else injection,
                    "compensation": None if terminal else compensation,
                    "npv_cumulative": npv_cumulative,
                    "active_wells": active_wells,
                },
                "wells": well_rows,
            }
        )
    return _rounded(
        {
            "model": meta.model,
            "t0": meta.t0.isoformat(),
            "n_control_dates": n_control_dates,
            "n_intervals": meta.n_intervals,
            "wells": wells,
            "field_norms": {
                "compensation": {
                    "min": COMPENSATION_NORM_MIN,
                    "max": COMPENSATION_NORM_MAX,
                }
            },
            "steps": steps,
        }
    )


def build_trace(artifact: RunArtifact) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for entry in artifact.trace:
        by_step = grouped.setdefault(entry.well, {})
        by_step.setdefault(str(entry.control_step), []).append(
            {
                "rule": entry.rule.name,
                "inputs": dict(entry.inputs),
                "decision": entry.decision,
            }
        )
    return grouped


def _write_json(data: dict[str, Any], out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return out


def export_timeline_json(
    artifact: RunArtifact, densities: dict[str, float], out_path: str | Path
) -> Path:
    return _write_json(build_timeline(artifact, densities), out_path)


def export_trace_json(artifact: RunArtifact, out_path: str | Path) -> Path:
    return _write_json(build_trace(artifact), out_path)
