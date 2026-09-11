from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from backend.contexts.economics.domain.errors import BaseCaseError
from backend.contexts.reservoir.domain.response import (
    ActiveControlMode,
    IntervalResponse,
    StateAtDate,
)
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.shared.json_io import read_json


def states_by_well_from_artifact(
    artifact: ResponseArtifact,
) -> dict[str, tuple[StateAtDate, ...]]:
    grouped: dict[str, list[StateAtDate]] = {}
    for state in artifact.state_at_date:
        grouped.setdefault(state.well, []).append(state)
    return {
        well: tuple(sorted(states, key=lambda item: item.deck_date_index))
        for well, states in grouped.items()
    }


def responses_by_well_from_artifact(
    artifact: ResponseArtifact,
) -> dict[str, tuple[IntervalResponse, ...]]:
    grouped: dict[str, list[IntervalResponse]] = {}
    for response in artifact.interval_response:
        grouped.setdefault(response.well, []).append(response)
    return {
        well: tuple(sorted(items, key=lambda item: item.control_step))
        for well, items in grouped.items()
    }


def interval_start_dates(
    deck_dates: Sequence[date], t0_deck_date_index: int, n_intervals: int
) -> tuple[date, ...]:
    if t0_deck_date_index + n_intervals > len(deck_dates):
        raise BaseCaseError(
            f"{len(deck_dates)} deck dates are not enough for {n_intervals} intervals "
            f"from t0_deck_date_index={t0_deck_date_index}"
        )
    return tuple(
        deck_dates[t0_deck_date_index + control_step]
        for control_step in range(n_intervals)
    )


def save_response_artifact(artifact: ResponseArtifact, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_run_id": artifact.source_run_id,
        "response_hash": artifact.response_hash,
        "state_at_date": [
            {
                "deck_date_index": state.deck_date_index,
                "well": state.well,
                "liquid_rate": state.liquid_rate,
                "oil_rate": state.oil_rate,
                "injection_rate": state.injection_rate,
                "thp": state.thp,
                "bhp": state.bhp,
                "well_efficiency": state.well_efficiency,
                "active_control_mode": state.active_control_mode.value,
            }
            for state in artifact.state_at_date
        ],
        "interval_response": [
            {
                "control_step": response.control_step,
                "well": response.well,
                "oil_mass_delta": response.oil_mass_delta,
                "liquid_volume_delta": response.liquid_volume_delta,
                "injection_volume_delta": response.injection_volume_delta,
            }
            for response in artifact.interval_response
        ],
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)
    return target


def load_response_artifact(path: Path | str) -> ResponseArtifact:
    source = Path(path)
    if not source.is_file():
        raise BaseCaseError(
            f"base run response artifact not found: {source}. "
            "It is produced by a real OPM run "
            "(`bridge.run_base_case` -> `save_response_artifact`) and is never substituted by synthetic data."
        )
    payload = read_json(source)
    return ResponseArtifact(
        source_run_id=payload["source_run_id"],
        response_hash=payload["response_hash"],
        state_at_date=tuple(
            StateAtDate(
                deck_date_index=item["deck_date_index"],
                well=item["well"],
                liquid_rate=item["liquid_rate"],
                oil_rate=item["oil_rate"],
                injection_rate=item["injection_rate"],
                thp=item["thp"],
                bhp=item["bhp"],
                well_efficiency=item["well_efficiency"],
                active_control_mode=ActiveControlMode(item["active_control_mode"]),
            )
            for item in payload["state_at_date"]
        ),
        interval_response=tuple(
            IntervalResponse(
                control_step=item["control_step"],
                well=item["well"],
                oil_mass_delta=item["oil_mass_delta"],
                liquid_volume_delta=item["liquid_volume_delta"],
                injection_volume_delta=item["injection_volume_delta"],
            )
            for item in payload["interval_response"]
        ),
    )
