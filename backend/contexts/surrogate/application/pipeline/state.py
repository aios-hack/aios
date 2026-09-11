from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.contexts.simulation.domain.perturbation_design import PlanConfig

logger = logging.getLogger("backend.contexts.surrogate.application.pipeline")


PILOT_CONFIG = PlanConfig(
    n_level_scenarios=110,
    n_unreachable_scenarios=40,
    n_shutdown_scenarios=35,
    n_conversion_scenarios=14,
)
EXTRA_CONFIG = PlanConfig(
    n_level_scenarios=275,
    n_unreachable_scenarios=100,
    n_shutdown_scenarios=87,
    n_conversion_scenarios=37,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CycleState:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.path = data_root / "cycle.json"
        self.events_path = data_root / "cycle-events.jsonl"
        default: dict[str, Any] = {
            "format": "aios.model-z-cycle.v1",
            "updated_at": _now(),
            "phase": "waiting_pilot",
            "stages": [
                {
                    "id": "pilot-200",
                    "title": "Pilot 200",
                    "dataset_root": "dataset-main",
                    "target": 200,
                    "seed": 20260816,
                    "status": "running",
                    "snapshot": "cycle/pilot-200.json",
                },
                {
                    "id": "extra-500",
                    "title": "Extension 500",
                    "dataset_root": "dataset-extra-500",
                    "target": 500,
                    "seed": 20260817,
                    "status": "queued",
                    "snapshot": "cycle/extra-500.json",
                },
                {
                    "id": "combined-700",
                    "title": "Total 700",
                    "dataset_root": "",
                    "target": 700,
                    "status": "queued",
                    "report": "model-task34-700/training_report.json",
                },
            ],
        }
        self.data_root.mkdir(parents=True, exist_ok=True)
        (self.data_root / "cycle").mkdir(parents=True, exist_ok=True)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = None
        self.payload = (
            loaded
            if isinstance(loaded, dict)
            and loaded.get("format") == "aios.model-z-cycle.v1"
            else default
        )
        self.save()

    def stage(self, stage_id: str) -> dict[str, Any]:
        return next(item for item in self.payload["stages"] if item["id"] == stage_id)

    def update_stage(self, stage_id: str, **changes: Any) -> None:
        self.stage(stage_id).update(changes)
        self.payload["updated_at"] = _now()
        self.save()

    def phase(self, value: str) -> None:
        self.payload["phase"] = value
        if value != "failed":
            self.payload.pop("error", None)
        self.payload["updated_at"] = _now()
        self.save()
        self.event({"phase": value})

    def event(self, payload: dict[str, Any]) -> None:
        row = {"at": _now(), **payload}
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        logger.info(json.dumps(row, ensure_ascii=False, allow_nan=False))

    def save(self) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)


__all__ = [
    "CycleState",
    "EXTRA_CONFIG",
    "PILOT_CONFIG",
]
