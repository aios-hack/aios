from __future__ import annotations
import json
from datetime import date
from pathlib import Path
from typing import Any
from backend.contexts.schedule.domain.schedule import (
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from backend.shared.json_io import read_json

def _load_meta(data: dict[str, Any]) -> ScheduleMeta:
    return ScheduleMeta(
        model=data["model"],
        t0=date.fromisoformat(data["t0"]),
        n_control_dates=data["n_control_dates"],
        n_intervals=data["n_intervals"],
        wells=tuple(data["wells"]),
        history_prefix_hash=data["history_prefix_hash"],
        fixed_events_hash=data["fixed_events_hash"],
        control_events_hash=data["control_events_hash"],
        provenance=data["provenance"],
    )


def _load_well_state(data: dict[str, Any]) -> WellState:
    return WellState(
        availability=Availability[data["availability"]],
        role=Role[data["role"]],
        operating_status=OperatingStatus[data["operating_status"]],
        setpoint=data["setpoint"],
    )


def _load_fixed_deck_event(data: dict[str, Any]) -> FixedDeckEvent:
    return FixedDeckEvent(
        control_step=data["control_step"],
        well=data["well"],
        operator=data["operator"],
        raw_args=tuple(data["raw_args"]),
    )


def _load_control_event(data: dict[str, Any]) -> ControlEvent:
    return ControlEvent(
        control_step=data["control_step"],
        well=data["well"],
        kind=EventKind[data["kind"]],
        value=data["value"],
    )


def _load_schedule(data: dict[str, Any]) -> Schedule:
    return Schedule(
        meta=_load_meta(data["meta"]),
        initial_state={
            well: _load_well_state(state)
            for well, state in data["initial_state"].items()
        },
        fixed_deck_events=tuple(
            _load_fixed_deck_event(e) for e in data["fixed_deck_events"]
        ),
        control_events=tuple(_load_control_event(e) for e in data["control_events"]),
    )


def load_schedule_json(path: str | Path) -> Schedule:
    return _load_schedule(read_json(Path(path)))
