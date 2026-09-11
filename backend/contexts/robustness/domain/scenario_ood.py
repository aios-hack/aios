"""Scenario-level PCA/kNN input-density guard for direct NPV features."""

from __future__ import annotations

from backend.contexts.robustness.domain.errors import (
    ScenarioDensityError,
)

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import Tensor

FORMAT = "aios.surrogate-scenario-density-domain.v1"


def _tensor_bytes(value: Tensor) -> bytes:
    return value.detach().cpu().contiguous().numpy().tobytes()


@dataclass(frozen=True, slots=True)
class ScenarioDensityDomain:
    dataset_hash: str
    active_indices: Tensor
    scaler_mean: Tensor
    scaler_scale: Tensor
    pca_mean: Tensor
    pca_components: Tensor
    pca_explained_variance: Tensor
    train_embeddings: Tensor
    neighbors: int
    threshold: float
    threshold_quantile: float
    validation_scenario_count: int
    validation_inside_count: int
    feature_width: int = 2908
    version: str = ""

    def __post_init__(self) -> None:
        tensors = (
            self.scaler_mean,
            self.scaler_scale,
            self.pca_mean,
            self.pca_components,
            self.pca_explained_variance,
            self.train_embeddings,
        )
        if len(self.dataset_hash) != 64:
            raise ScenarioDensityError("invalid scenario-density dataset hash")
        if self.active_indices.ndim != 1 or self.active_indices.dtype != torch.int64:
            raise ScenarioDensityError("invalid active feature index")
        active = len(self.active_indices)
        components = self.pca_components.shape[0]
        if (
            self.feature_width < 1
            or active < 1
            or self.pca_components.shape != (components, active)
            or self.scaler_mean.shape != (active,)
            or self.scaler_scale.shape != (active,)
            or self.pca_mean.shape != (active,)
            or self.pca_explained_variance.shape != (components,)
            or self.train_embeddings.ndim != 2
            or self.train_embeddings.shape[1] != components
        ):
            raise ScenarioDensityError("scenario-density tensor axes differ")
        if (
            int(self.active_indices.min()) < 0
            or int(self.active_indices.max()) >= self.feature_width
        ):
            raise ScenarioDensityError("active feature index is outside feature width")
        if len({int(value) for value in self.active_indices}) != active:
            raise ScenarioDensityError("active feature index contains duplicates")
        if any(not bool(torch.isfinite(value).all()) for value in tensors):
            raise ScenarioDensityError(
                "scenario-density artifact contains non-finite values"
            )
        if bool((self.scaler_scale <= 0.0).any()) or bool(
            (self.pca_explained_variance <= 0.0).any()
        ):
            raise ScenarioDensityError("scenario-density scales must be positive")
        if not 1 <= self.neighbors <= len(self.train_embeddings):
            raise ScenarioDensityError("invalid scenario-density neighbor count")
        if not math.isfinite(self.threshold) or self.threshold < 0.0:
            raise ScenarioDensityError("invalid scenario-density threshold")
        if not 0.5 <= self.threshold_quantile < 1.0:
            raise ScenarioDensityError("invalid scenario-density threshold quantile")
        if not 0 <= self.validation_inside_count <= self.validation_scenario_count:
            raise ScenarioDensityError("invalid scenario-density validation counts")
        expected = self._fingerprint()
        if self.version and self.version != expected:
            raise ScenarioDensityError("scenario-density fingerprint differs")
        object.__setattr__(self, "version", expected)

    @property
    def n_components(self) -> int:
        return int(self.pca_components.shape[0])

    def _fingerprint(self) -> str:
        metadata = {
            "format": FORMAT,
            "dataset_hash": self.dataset_hash,
            "feature_width": self.feature_width,
            "neighbors": self.neighbors,
            "threshold": self.threshold,
            "threshold_quantile": self.threshold_quantile,
            "validation_scenario_count": self.validation_scenario_count,
            "validation_inside_count": self.validation_inside_count,
        }
        digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode("utf-8"))
        for value in (
            self.active_indices,
            self.scaler_mean,
            self.scaler_scale,
            self.pca_mean,
            self.pca_components,
            self.pca_explained_variance,
            self.train_embeddings,
        ):
            digest.update(_tensor_bytes(value))
        return digest.hexdigest()

    def embed(self, vectors: Tensor) -> Tensor:
        values = vectors.detach().cpu().to(torch.float64)
        if values.ndim == 1:
            values = values.unsqueeze(0)
        if values.ndim != 2 or values.shape[1] != self.feature_width:
            raise ScenarioDensityError("scenario vector width differs from domain")
        if not bool(torch.isfinite(values).all()):
            raise ScenarioDensityError("scenario vector contains non-finite values")
        selected = values[:, self.active_indices]
        standardized = (selected - self.scaler_mean) / self.scaler_scale
        projected = (standardized - self.pca_mean) @ self.pca_components.T
        return projected / torch.sqrt(self.pca_explained_variance)

    def scores(self, vectors: Tensor) -> Tensor:
        embeddings = self.embed(vectors)
        distances = torch.cdist(embeddings, self.train_embeddings)
        return torch.kthvalue(distances, self.neighbors, dim=1).values

    def score(self, vector: Tensor) -> float:
        return float(self.scores(vector)[0])

    def is_inside(self, vector: Tensor) -> bool:
        return self.score(vector) <= self.threshold

    def save(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "format": FORMAT,
            "dataset_hash": self.dataset_hash,
            "feature_set": "full",
            "feature_width": self.feature_width,
            "fit_bucket": "train",
            "threshold_bucket": "validation",
            "historical_test_read": False,
            "blind_response_read": False,
            "neighbors": self.neighbors,
            "threshold": self.threshold,
            "threshold_quantile": self.threshold_quantile,
            "validation_scenario_count": self.validation_scenario_count,
            "validation_inside_count": self.validation_inside_count,
            "active_indices": self.active_indices,
            "scaler_mean": self.scaler_mean,
            "scaler_scale": self.scaler_scale,
            "pca_mean": self.pca_mean,
            "pca_components": self.pca_components,
            "pca_explained_variance": self.pca_explained_variance,
            "train_embeddings": self.train_embeddings,
            "version": self.version,
        }
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        torch.save(payload, temporary)
        temporary.replace(destination)
        return destination

    @classmethod
    def load(cls, path: Path | str) -> ScenarioDensityDomain:
        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        if payload.get("format") != FORMAT:
            raise ScenarioDensityError("unsupported scenario-density format")
        if (
            payload.get("feature_set") != "full"
            or payload.get("fit_bucket") != "train"
            or payload.get("threshold_bucket") != "validation"
            or payload.get("historical_test_read") is not False
            or payload.get("blind_response_read") is not False
        ):
            raise ScenarioDensityError("scenario-density provenance is unsafe")
        return cls(
            dataset_hash=str(payload["dataset_hash"]),
            feature_width=int(payload["feature_width"]),
            active_indices=payload["active_indices"],
            scaler_mean=payload["scaler_mean"],
            scaler_scale=payload["scaler_scale"],
            pca_mean=payload["pca_mean"],
            pca_components=payload["pca_components"],
            pca_explained_variance=payload["pca_explained_variance"],
            train_embeddings=payload["train_embeddings"],
            neighbors=int(payload["neighbors"]),
            threshold=float(payload["threshold"]),
            threshold_quantile=float(payload["threshold_quantile"]),
            validation_scenario_count=int(payload["validation_scenario_count"]),
            validation_inside_count=int(payload["validation_inside_count"]),
            version=str(payload["version"]),
        )
