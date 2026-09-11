from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.surrogate.domain.errors import ModelZContextError
from backend.contexts.surrogate.domain.features import FeatureContext, HistoryTargets
from backend.shared.json_io import read_json

__all__ = ["ModelZFeatureArtifact"]


@dataclass(frozen=True, slots=True)
class ModelZFeatureArtifact:
    context: FeatureContext
    dataset_hash: str
    lambda_source_hash: str
    n_training_scenarios: int

    FORMAT = "aios.model-z-feature-context.v1"

    def save(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_payload(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return destination

    def to_payload(self) -> dict[str, Any]:
        return {
            "format": self.FORMAT,
            "dataset_hash": self.dataset_hash,
            "lambda_source_hash": self.lambda_source_hash,
            "n_training_scenarios": self.n_training_scenarios,
            "control_dates": [item.isoformat() for item in self.context.control_dates],
            "history_start": self.context.history_start.isoformat(),
            "history_prefix_hash": self.context.history_prefix_hash,
            "history_targets": {
                well: {
                    "target_liquid_m3": item.target_liquid_m3,
                    "target_injection_m3": item.target_injection_m3,
                    "event_count": item.event_count,
                }
                for well, item in sorted(self.context.history_targets.items())
            },
            "static_features": {
                well: dict(sorted(values.items()))
                for well, values in sorted(self.context.static_features.items())
            },
            "lambda_windows": [_lambda_payload(item) for item in self.context.lambda_windows],
        }

    @classmethod
    def load(cls, path: Path | str) -> "ModelZFeatureArtifact":
        payload = read_json(Path(path))
        if payload.get("format") != cls.FORMAT:
            raise ModelZContextError(f"unknown context format: {payload.get('format')!r}")
        context = FeatureContext(
            control_dates=tuple(date.fromisoformat(item) for item in payload["control_dates"]),
            history_start=date.fromisoformat(payload["history_start"]),
            history_prefix_hash=str(payload["history_prefix_hash"]),
            history_targets={
                well: HistoryTargets(**values)
                for well, values in payload["history_targets"].items()
            },
            static_features={
                well: {name: float(value) for name, value in values.items()}
                for well, values in payload["static_features"].items()
            },
            lambda_windows=tuple(
                _lambda_from_payload(item) for item in payload["lambda_windows"]
            ),
        )
        return cls(
            context=context,
            dataset_hash=str(payload["dataset_hash"]),
            lambda_source_hash=str(payload["lambda_source_hash"]),
            n_training_scenarios=int(payload["n_training_scenarios"]),
        )


def _lambda_payload(item: Lambda) -> dict[str, Any]:
    return {
        "window_start": item.window_start.isoformat(),
        "window_end": item.window_end.isoformat(),
        "producers": list(item.producers),
        "injectors": list(item.injectors),
        "matrix": [list(row) for row in item.matrix],
        "lag_months": item.lag_months,
        "amplitude": item.amplitude,
        "stability": item.stability,
        "rank": item.rank,
        "condition_number": item.condition_number,
        "achievability_ok": dict(sorted(item.achievability_ok.items())),
    }


def _lambda_from_payload(payload: Mapping[str, Any]) -> Lambda:
    return Lambda(
        window_start=date.fromisoformat(str(payload["window_start"])),
        window_end=date.fromisoformat(str(payload["window_end"])),
        producers=tuple(str(item) for item in payload["producers"]),
        injectors=tuple(str(item) for item in payload["injectors"]),
        matrix=tuple(tuple(float(value) for value in row) for row in payload["matrix"]),
        lag_months=int(payload["lag_months"]),
        amplitude=float(payload["amplitude"]),
        stability=float(payload["stability"]),
        rank=int(payload["rank"]),
        condition_number=float(payload["condition_number"]),
        achievability_ok={
            str(well): bool(value) for well, value in payload["achievability_ok"].items()
        },
    )
