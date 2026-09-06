"""Validation-selected averaging ensemble for physical trajectory models."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from surrogate.features import SurrogateInput
from surrogate.model import TrajectorySurrogate
from surrogate.ood import ScoredPrediction
from surrogate.raw_model_output import RawModelOutput, RawWellStepPrediction

FORMAT = "aios.trajectory-ensemble.v1"


class TrajectoryEnsembleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TrajectoryEnsemble:
    models: tuple[TrajectorySurrogate, ...]
    weights: tuple[float, ...]
    member_paths: tuple[Path, ...]
    version: str = ""

    def __post_init__(self) -> None:
        if not self.models or len(self.models) != len(self.weights):
            raise TrajectoryEnsembleError("оси models/weights пусты или разошлись")
        if len(self.member_paths) != len(self.models):
            raise TrajectoryEnsembleError("оси member_paths/models разошлись")
        if any(not math.isfinite(value) or value <= 0.0 for value in self.weights):
            raise TrajectoryEnsembleError("ensemble weights должны быть положительными")
        total = math.fsum(self.weights)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1.0e-12):
            raise TrajectoryEnsembleError("ensemble weights должны суммироваться в единицу")
        first = self.models[0]
        for model in self.models[1:]:
            if model.dataset_hash != first.dataset_hash:
                raise TrajectoryEnsembleError("members обучены на разных datasets")
            if model.wells != first.wells:
                raise TrajectoryEnsembleError("members имеют разные оси wells")
            if model.static_feature_names != first.static_feature_names:
                raise TrajectoryEnsembleError("members имеют разную статику")
            if model.domain != first.domain:
                raise TrajectoryEnsembleError("members имеют разные OOD domains")
        object.__setattr__(self, "version", self.version or self._fingerprint())

    @property
    def wells(self) -> tuple[str, ...]:
        return self.models[0].wells

    @property
    def static_feature_names(self) -> tuple[str, ...]:
        return self.models[0].static_feature_names

    @property
    def dataset_hash(self) -> str:
        return self.models[0].dataset_hash

    def _fingerprint(self) -> str:
        payload = {
            "format": FORMAT,
            "members": [model.version for model in self.models],
            "weights": self.weights,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def predict(self, candidate: SurrogateInput) -> ScoredPrediction:
        predictions = tuple(model.predict(candidate) for model in self.models)
        reference = predictions[0]
        for other in predictions[1:]:
            if other.ood != reference.ood:
                raise TrajectoryEnsembleError("OOD score разошёлся между members")
        nodes = []
        fields = (
            "oil_mass_delta",
            "liquid_volume_delta",
            "injection_volume_delta",
            "liquid_rate",
            "injection_rate",
            "bhp",
        )
        member_nodes = tuple(item.output.nodes for item in predictions)
        for rows in zip(*member_nodes):
            first = rows[0]
            if any(
                (row.well, row.control_step) != (first.well, first.control_step)
                for row in rows[1:]
            ):
                raise TrajectoryEnsembleError("порядок nodes разошёлся")
            averaged = {
                field: math.fsum(
                    weight * getattr(row, field)
                    for weight, row in zip(self.weights, rows)
                )
                for field in fields
            }
            nodes.append(
                RawWellStepPrediction(
                    well=first.well,
                    control_step=first.control_step,
                    **averaged,
                )
            )
        output = RawModelOutput(
            canonical_schedule_hash=candidate.canonical_schedule_hash,
            wells=candidate.wells,
            nodes=tuple(nodes),
        )
        return ScoredPrediction(output=output, ood=reference.ood)

    @classmethod
    def load(cls, path: Path | str) -> TrajectoryEnsemble:
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload.get("format") != FORMAT:
            raise TrajectoryEnsembleError(
                f"неизвестный ensemble format: {payload.get('format')}"
            )
        member_paths = tuple(source.parent / item for item in payload["members"])
        ensemble = cls(
            models=tuple(TrajectorySurrogate.load(item) for item in member_paths),
            weights=tuple(float(value) for value in payload["weights"]),
            member_paths=member_paths,
            version=str(payload["version"]),
        )
        if ensemble._fingerprint() != ensemble.version:
            raise TrajectoryEnsembleError("ensemble fingerprint не совпадает")
        return ensemble

    @classmethod
    def write_manifest(
        cls,
        checkpoints: tuple[Path, ...],
        weights: tuple[float, ...],
        destination: Path,
    ) -> TrajectoryEnsemble:
        resolved = tuple(path.resolve() for path in checkpoints)
        ensemble = cls(
            models=tuple(TrajectorySurrogate.load(path) for path in resolved),
            weights=weights,
            member_paths=resolved,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": FORMAT,
            "members": [
                os.path.relpath(path, destination.parent) for path in resolved
            ],
            "weights": ensemble.weights,
            "member_versions": [model.version for model in ensemble.models],
            "dataset_hash": ensemble.dataset_hash,
            "version": ensemble.version,
        }
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return ensemble
