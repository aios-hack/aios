from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from aios_backend.core.contracts import (
    ActiveControlMode,
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    FinalNpvArtifact,
    FixedDeckEvent,
    Groups,
    IntervalResponse,
    Lambda,
    LineItems,
    NpvTable,
    OperatingStatus,
    Role,
    Rule,
    RunArtifact,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    TraceEntry,
    WellOutage,
    WellState,
)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def dump_bundle(artifact: RunArtifact, path: str | Path) -> None:
    text = json.dumps(
        _to_jsonable(artifact), ensure_ascii=False, sort_keys=True, indent=2
    )
    Path(path).write_text(text, encoding="utf-8")


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


def _load_state_at_date(data: dict[str, Any]) -> StateAtDate:
    return StateAtDate(
        deck_date_index=data["deck_date_index"],
        well=data["well"],
        liquid_rate=data["liquid_rate"],
        oil_rate=data["oil_rate"],
        injection_rate=data["injection_rate"],
        thp=data["thp"],
        bhp=data["bhp"],
        well_efficiency=data["well_efficiency"],
        active_control_mode=ActiveControlMode[data["active_control_mode"]],
    )


def _load_interval_response(data: dict[str, Any]) -> IntervalResponse:
    return IntervalResponse(
        control_step=data["control_step"],
        well=data["well"],
        oil_mass_delta=data["oil_mass_delta"],
        liquid_volume_delta=data["liquid_volume_delta"],
        injection_volume_delta=data["injection_volume_delta"],
    )


def _load_line_items(data: dict[str, Any]) -> LineItems:
    return LineItems(**data)


def _load_npv_table(data: dict[str, Any]) -> NpvTable:
    return NpvTable(
        by_year={int(k): _load_line_items(v) for k, v in data["by_year"].items()},
        by_month={int(k): _load_line_items(v) for k, v in data["by_month"].items()},
        by_well={k: _load_line_items(v) for k, v in data["by_well"].items()},
        npv_methodology=data["npv_methodology"],
    )


def _load_trace_entry(data: dict[str, Any]) -> TraceEntry:
    return TraceEntry(
        control_step=data["control_step"],
        well=data["well"],
        rule=Rule[data["rule"]],
        inputs=dict(data["inputs"]),
        decision=data["decision"],
    )


def _load_groups(data: dict[str, Any]) -> Groups:
    return Groups(
        groups={k: tuple(v) for k, v in data["groups"].items()},
        lambda_hash=data["lambda_hash"],
        group_hash=data["group_hash"],
    )


def _load_lambda(data: dict[str, Any]) -> Lambda:
    return Lambda(
        window_start=date.fromisoformat(data["window_start"]),
        window_end=date.fromisoformat(data["window_end"]),
        producers=tuple(data["producers"]),
        injectors=tuple(data["injectors"]),
        matrix=tuple(tuple(row) for row in data["matrix"]),
        lag_months=data["lag_months"],
        amplitude=data["amplitude"],
        stability=data["stability"],
        rank=data["rank"],
        condition_number=data["condition_number"],
        achievability_ok=dict(data["achievability_ok"]),
    )


def _load_constraints(data: dict[str, Any]) -> Constraints:
    return Constraints(
        injection_limits={int(k): v for k, v in data["injection_limits"].items()},
        liquid_limits={int(k): v for k, v in data["liquid_limits"].items()},
        production_floors={int(k): v for k, v in data["production_floors"].items()},
        watercut_limits={int(k): v for k, v in data["watercut_limits"].items()},
        well_outages=tuple(
            WellOutage(
                well=o["well"],
                control_step_from=o["control_step_from"],
                control_step_to=o["control_step_to"],
            )
            for o in data["well_outages"]
        ),
        infrastructure=dict(data["infrastructure"]),
    )


def _load_final_npv(data: dict[str, Any] | None) -> FinalNpvArtifact | None:
    if data is None:
        return None
    return FinalNpvArtifact(
        npv_table=_load_npv_table(data["npv_table"]),
        npv_methodology=data["npv_methodology"],
        source_run_id=data["source_run_id"],
        source_response_hash=data["source_response_hash"],
        economics_config_hash=data["economics_config_hash"],
        methodology_version_hash=data["methodology_version_hash"],
    )


def load_bundle(path: str | Path) -> RunArtifact:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return RunArtifact(
        config_hash=data["config_hash"],
        schedule=_load_schedule(data["schedule"]),
        state_at_date=tuple(_load_state_at_date(s) for s in data["state_at_date"]),
        interval_response=tuple(
            _load_interval_response(r) for r in data["interval_response"]
        ),
        npv_table=_load_npv_table(data["npv_table"]),
        trace=tuple(_load_trace_entry(t) for t in data["trace"]),
        groups=_load_groups(data["groups"]),
        lambda_=_load_lambda(data["lambda_"]),
        constraints=_load_constraints(data["constraints"]),
        converged=data["converged"],
        self_consistent=data["self_consistent"],
        final_npv=_load_final_npv(data["final_npv"]),
    )
