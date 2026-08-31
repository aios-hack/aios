"""Inference runtime for the deployed direct scenario-level NPV head."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import torch
from torch import Tensor

from backend.core.contracts import N_INTERVALS

from .features import SurrogateInput
from .model import _features

FORMAT = "aios.surrogate-scenario-npv-head.v1"
BASE_FEATURES = 21
TEMPORAL_BINS = 28
KernelName = Literal["linear", "poly2", "rbf"]
FeatureSet = Literal["global", "temporal", "full"]


class ScenarioNpvHeadError(ValueError):
    pass


def scenario_feature_vector(
    x: Tensor,
    well_index: Tensor,
    *,
    n_wells: int,
    feature_set: FeatureSet = "full",
) -> Tensor:
    """Collapse the complete 224 x well schedule tensor exactly as at training."""

    if x.ndim != 2 or x.shape[1] < BASE_FEATURES:
        raise ScenarioNpvHeadError(
            f"ожидался x[:, >={BASE_FEATURES}], получено {x.shape}"
        )
    if len(x) != N_INTERVALS * n_wells or well_index.shape != (len(x),):
        raise ScenarioNpvHeadError("scenario tensor не покрывает 224 × wells")
    if n_wells < 1:
        raise ScenarioNpvHeadError("n_wells должен быть положительным")
    if bool(((well_index < 0) | (well_index >= n_wells)).any()):
        raise ScenarioNpvHeadError("индекс скважины вышел за допустимый диапазон")

    base = x[:, :BASE_FEATURES].to(dtype=torch.float64)
    step_index = torch.round(base[:, 11] * (N_INTERVALS - 1)).to(torch.long)
    if bool(((step_index < 0) | (step_index >= N_INTERVALS)).any()):
        raise ScenarioNpvHeadError("календарный индекс вышел за 0…223")
    flat_index = step_index * n_wells + well_index.to(torch.long)
    if len(torch.unique(flat_index)) != len(flat_index):
        raise ScenarioNpvHeadError("scenario tensor содержит дубли step × well")

    grid = torch.empty(N_INTERVALS * n_wells, BASE_FEATURES, dtype=torch.float64)
    grid[flat_index] = base
    grid = grid.reshape(N_INTERVALS, n_wells, BASE_FEATURES)
    rows = grid.reshape(-1, BASE_FEATURES)
    global_features = torch.cat(
        (rows.mean(dim=0), rows.std(dim=0, unbiased=False), rows.amin(dim=0), rows.amax(dim=0))
    )
    if feature_set == "global":
        return global_features
    if N_INTERVALS % TEMPORAL_BINS:
        raise ScenarioNpvHeadError("224 интервала не делятся на temporal bins")
    bin_width = N_INTERVALS // TEMPORAL_BINS
    bins = grid.reshape(TEMPORAL_BINS, bin_width * n_wells, BASE_FEATURES)
    temporal = torch.cat(
        (bins.mean(dim=1), bins.std(dim=1, unbiased=False)), dim=1
    ).reshape(-1)
    if feature_set == "temporal":
        return torch.cat((global_features, temporal))
    if feature_set != "full":
        raise ScenarioNpvHeadError(
            f"runtime поддерживает deployed feature_set global/temporal/full, получено {feature_set!r}"
        )
    controls = grid[:, :, :8]
    by_well = torch.cat(
        (controls.mean(dim=0), controls.std(dim=0, unbiased=False)), dim=1
    ).reshape(-1)
    return torch.cat((global_features, temporal, by_well))


def _kernel(left: Tensor, right: Tensor, name: KernelName, gamma: float) -> Tensor:
    width = left.shape[1]
    if right.shape[1] != width:
        raise ScenarioNpvHeadError("ширина kernel features разошлась")
    if name == "linear":
        return left @ right.T / width
    if name == "poly2":
        return (left @ right.T / width + 1.0).square()
    if name == "rbf":
        distance = (
            left.square().sum(dim=1, keepdim=True)
            + right.square().sum(dim=1).unsqueeze(0)
            - 2.0 * left @ right.T
        ).clamp_min(0.0)
        return torch.exp(-gamma * distance)
    raise ScenarioNpvHeadError(f"неизвестный kernel={name!r}")


@dataclass(slots=True)
class ScenarioNpvHead:
    wells: tuple[str, ...]
    static_feature_names: tuple[str, ...]
    feature_set: FeatureSet
    kernel: KernelName
    gamma: float
    feature_mean: Tensor
    feature_scale: Tensor
    centers: Tensor
    dual: Tensor
    target_mean_rub: float
    target_scale_rub: float
    dataset_hash: str
    target_provenance_hash: str = ""
    feature_provenance_hash: str = ""
    feature_context_sha256: str = ""
    calibration_slope: float = 1.0
    calibration_intercept_rub: float = 0.0
    version: str = ""
    _domain_radius_rms: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.static_feature_names) != 3 or not self.wells:
            raise ScenarioNpvHeadError("оси NPV head неполны")
        if self.kernel not in {"linear", "poly2", "rbf"}:
            raise ScenarioNpvHeadError(f"неизвестный kernel={self.kernel!r}")
        if self.feature_set not in {"global", "temporal", "full"}:
            raise ScenarioNpvHeadError(f"неподдержанный feature_set={self.feature_set!r}")
        if self.gamma <= 0.0 or not math.isfinite(self.gamma):
            raise ScenarioNpvHeadError("gamma должна быть конечной и положительной")
        if self.target_scale_rub <= 0.0 or not math.isfinite(self.target_scale_rub):
            raise ScenarioNpvHeadError("target scale должна быть положительной")
        if self.calibration_slope <= 0.0 or not math.isfinite(self.calibration_slope):
            raise ScenarioNpvHeadError("calibration slope должна быть положительной")
        if not math.isfinite(self.calibration_intercept_rub):
            raise ScenarioNpvHeadError("calibration intercept должна быть конечной")
        if self.centers.ndim != 2 or self.dual.shape != (len(self.centers),):
            raise ScenarioNpvHeadError("оси centers/dual разошлись")
        width = self.centers.shape[1]
        if self.feature_mean.shape != (width,) or self.feature_scale.shape != (width,):
            raise ScenarioNpvHeadError("оси feature scaler разошлись")
        if not bool((self.feature_scale > 0.0).all()):
            raise ScenarioNpvHeadError("feature scale должна быть положительной")
        if not all(
            bool(torch.isfinite(value).all())
            for value in (self.feature_mean, self.feature_scale, self.centers, self.dual)
        ):
            raise ScenarioNpvHeadError("NPV head содержит нечисловые тензоры")
        if len(self.centers) < 2:
            raise ScenarioNpvHeadError(
                "NPV head нужны минимум два training center для domain gate"
            )
        # Independent min/max checks miss unseen combinations of otherwise
        # familiar controls.  Measure joint support in the exact standardized
        # scenario-feature space consumed by the economic kernel.
        distances = torch.cdist(self.centers, self.centers) / math.sqrt(width)
        distances.fill_diagonal_(math.inf)
        radius = float(distances.amin(dim=1).amax())
        if radius <= 0.0 or not math.isfinite(radius):
            raise ScenarioNpvHeadError(
                "training centers не задают конечную joint-domain область"
            )
        self._domain_radius_rms = radius

    @property
    def domain_radius_rms(self) -> float:
        """Largest leave-one-out training-neighbour distance in RMS units."""

        return self._domain_radius_rms

    def domain_distance_vectors(self, vectors: Tensor) -> Tensor:
        """Distance to joint training support in standardized RMS units."""

        if vectors.ndim != 2 or vectors.shape[1:] != self.feature_mean.shape:
            raise ScenarioNpvHeadError(
                f"feature vectors {vectors.shape} несовместимы с {self.feature_mean.shape}"
            )
        standardized = (vectors.to(torch.float64) - self.feature_mean) / self.feature_scale
        return (
            torch.cdist(standardized, self.centers) / math.sqrt(self.centers.shape[1])
        ).amin(dim=1)

    def domain_score_vectors(self, vectors: Tensor) -> Tensor:
        """Zero inside joint train support; relative excess outside it."""

        return (self.domain_distance_vectors(vectors) / self._domain_radius_rms - 1.0).clamp_min(
            0.0
        )

    def predict_vectors(self, vectors: Tensor) -> Tensor:
        if vectors.ndim != 2 or vectors.shape[1:] != self.feature_mean.shape:
            raise ScenarioNpvHeadError(
                f"feature vectors {vectors.shape} несовместимы с {self.feature_mean.shape}"
            )
        standardized = (vectors.to(torch.float64) - self.feature_mean) / self.feature_scale
        raw = self.target_mean_rub + self.target_scale_rub * (
            _kernel(standardized, self.centers, self.kernel, self.gamma) @ self.dual
        )
        return self.calibration_intercept_rub + self.calibration_slope * raw

    def predict(self, candidate: SurrogateInput) -> float:
        prediction, _ = self.predict_with_domain(candidate)
        return prediction

    def predict_with_domain(self, candidate: SurrogateInput) -> tuple[float, float]:
        """Return economic prediction and its mandatory joint OOD score."""

        if candidate.static_feature_names != self.static_feature_names:
            raise ScenarioNpvHeadError("статика кандидата не совпадает с NPV head")
        x, well_index = _features(candidate, self.wells, scenario_context=False)
        vector = scenario_feature_vector(
            x, well_index, n_wells=len(self.wells), feature_set=self.feature_set
        )
        batch = vector.unsqueeze(0)
        return (
            float(self.predict_vectors(batch)[0]),
            float(self.domain_score_vectors(batch)[0]),
        )

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        metadata = {
            "format": FORMAT,
            "wells": self.wells,
            "static_feature_names": self.static_feature_names,
            "feature_set": self.feature_set,
            "kernel": self.kernel,
            "gamma": self.gamma,
            "target_mean_rub": self.target_mean_rub,
            "target_scale_rub": self.target_scale_rub,
            "dataset_hash": self.dataset_hash,
            "calibration_slope": self.calibration_slope,
            "calibration_intercept_rub": self.calibration_intercept_rub,
        }
        if self.target_provenance_hash:
            metadata["target_provenance_hash"] = self.target_provenance_hash
        if self.feature_provenance_hash:
            metadata["feature_provenance_hash"] = self.feature_provenance_hash
        if self.feature_context_sha256:
            metadata["feature_context_sha256"] = self.feature_context_sha256
        digest.update(json.dumps(metadata, sort_keys=True).encode("utf-8"))
        for tensor in (self.feature_mean, self.feature_scale, self.centers, self.dual):
            digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
        return digest.hexdigest()

    @classmethod
    def load(cls, path: Path | str) -> "ScenarioNpvHead":
        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        if payload.get("format") != FORMAT:
            raise ScenarioNpvHeadError(f"неизвестный artifact: {payload.get('format')}")
        head = cls(
            wells=tuple(payload["wells"]),
            static_feature_names=tuple(payload["static_feature_names"]),
            feature_set=payload["feature_set"],
            kernel=payload["kernel"],
            gamma=float(payload["gamma"]),
            feature_mean=payload["feature_mean"].to(torch.float64),
            feature_scale=payload["feature_scale"].to(torch.float64),
            centers=payload["centers"].to(torch.float64),
            dual=payload["dual"].to(torch.float64),
            target_mean_rub=float(payload["target_mean_rub"]),
            target_scale_rub=float(payload["target_scale_rub"]),
            dataset_hash=str(payload["dataset_hash"]),
            target_provenance_hash=str(payload.get("target_provenance_hash") or ""),
            feature_provenance_hash=str(payload.get("feature_provenance_hash") or ""),
            feature_context_sha256=str(payload.get("feature_context_sha256") or ""),
            calibration_slope=float(payload.get("calibration_slope", 1.0)),
            calibration_intercept_rub=float(payload.get("calibration_intercept_rub", 0.0)),
            version=str(payload["version"]),
        )
        if head._fingerprint() != head.version:
            raise ScenarioNpvHeadError("NPV head fingerprint не совпадает")
        return head
