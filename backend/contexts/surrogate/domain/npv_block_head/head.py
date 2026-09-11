from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import Tensor

from backend.contexts.surrogate.domain.errors import BlockNpvHeadError
from backend.contexts.surrogate.domain.features import SurrogateInput
from backend.contexts.surrogate.domain.npv_block_head.kernel import (
    DEFAULT_BLOCKS,
    FORMAT,
    LEGACY_IMPLEMENTATION_HASHES,
    Mode,
    _block_kernel,
    block_implementation_hash,
)
from backend.contexts.surrogate.domain.npv_economic_features import (
    LEGACY_FEATURE_PROVENANCE_HASHES,
    feature_implementation_hash,
    scenario_feature_vector,
)
from backend.contexts.surrogate.domain.vectorize import build_features


@dataclass(slots=True)
class BlockKernelNpvHead:
    wells: tuple[str, ...]
    static_feature_names: tuple[str, ...]
    blocks: tuple[tuple[str, int, int], ...]
    active_widths: tuple[int, ...]
    block_weights: tuple[float, ...]
    mode: Mode
    ridge: float
    feature_mean: Tensor
    feature_scale: Tensor
    centers: Tensor
    dual: Tensor
    target_mean_rub: float
    target_scale_rub: float
    dataset_hash: str
    target_provenance_hash: str
    feature_provenance_hash: str
    feature_context_sha256: str
    implementation_hash: str
    calibration_slope: float = 1.0
    calibration_intercept_rub: float = 0.0
    physical_npv_weight: float = 0.0
    physical_ensemble_version: str = ""
    physical_blend_provenance_hash: str = ""
    version: str = ""

    def __post_init__(self) -> None:
        if len(self.static_feature_names) != 3 or not self.wells:
            raise BlockNpvHeadError("block head axes are incomplete")
        if self.mode not in {"joint", "additive"}:
            raise BlockNpvHeadError("block head mode differs")
        if self.blocks != DEFAULT_BLOCKS:
            raise BlockNpvHeadError("block head boundaries differ from runtime")
        if self.ridge <= 0.0 or not math.isfinite(self.ridge):
            raise BlockNpvHeadError("block ridge must be positive")
        if not (
            len(self.blocks) == len(self.active_widths) == len(self.block_weights) >= 2
        ):
            raise BlockNpvHeadError("block head block axes differ")
        width = self.centers.shape[1] if self.centers.ndim == 2 else -1
        if self.feature_mean.shape != (width,) or self.feature_scale.shape != (width,):
            raise BlockNpvHeadError("block head feature axes differ")
        if self.dual.shape != (len(self.centers),):
            raise BlockNpvHeadError("block head dual axis differs")
        if (
            any(
                start < 0
                or stop <= start
                or (index and start != self.blocks[index - 1][2])
                for index, (_, start, stop) in enumerate(self.blocks)
            )
            or self.blocks[-1][2] != width
        ):
            raise BlockNpvHeadError("block boundaries do not cover features")
        if any(
            width < 0
            or width > stop - start
            or (weight > 0.0 and width < 1)
            for (_, start, stop), width, weight in zip(
                self.blocks,
                self.active_widths,
                self.block_weights,
                strict=True,
            )
        ):
            raise BlockNpvHeadError("weighted block active widths must be positive")
        if any(
            item < 0.0 or not math.isfinite(item) for item in self.block_weights
        ) or not math.isclose(
            sum(self.block_weights), 1.0, rel_tol=0.0, abs_tol=1.0e-9
        ):
            raise BlockNpvHeadError("block weights must be finite and sum to one")
        if not bool((self.feature_scale > 0.0).all()):
            raise BlockNpvHeadError("block feature scale must be positive")
        if not all(
            bool(torch.isfinite(tensor).all())
            for tensor in (
                self.feature_mean,
                self.feature_scale,
                self.centers,
                self.dual,
            )
        ):
            raise BlockNpvHeadError("block head tensors must be finite")
        if not math.isfinite(self.target_mean_rub):
            raise BlockNpvHeadError("block target mean must be finite")
        if self.target_scale_rub <= 0.0 or not math.isfinite(self.target_scale_rub):
            raise BlockNpvHeadError("block target scale must be positive")
        if len(self.dataset_hash) != 64 or any(
            c not in "0123456789abcdef" for c in self.dataset_hash
        ):
            raise BlockNpvHeadError("invalid dataset provenance hash")
        for name, value in (
            ("target", self.target_provenance_hash),
            ("feature", self.feature_provenance_hash),
            ("context", self.feature_context_sha256),
            ("implementation", self.implementation_hash),
        ):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise BlockNpvHeadError(f"invalid {name} provenance hash")
        if self.feature_provenance_hash not in {
            feature_implementation_hash(),
            *LEGACY_FEATURE_PROVENANCE_HASHES,
        }:
            raise BlockNpvHeadError("feature implementation changed")
        if self.implementation_hash not in {
            block_implementation_hash(),
            *LEGACY_IMPLEMENTATION_HASHES,
        }:
            raise BlockNpvHeadError("block implementation changed")
        if self.calibration_slope <= 0.0 or not math.isfinite(self.calibration_slope):
            raise BlockNpvHeadError("block calibration slope must be positive")
        if not math.isfinite(self.calibration_intercept_rub):
            raise BlockNpvHeadError("block calibration intercept must be finite")
        if not math.isfinite(self.physical_npv_weight) or not (
            0.0 <= self.physical_npv_weight <= 1.0
        ):
            raise BlockNpvHeadError("physical NPV weight must be in [0, 1]")
        if self.physical_npv_weight > 0.0:
            for name, value in (
                ("ensemble version", self.physical_ensemble_version),
                ("blend provenance", self.physical_blend_provenance_hash),
            ):
                if len(value) != 64 or any(
                    item not in "0123456789abcdef" for item in value
                ):
                    raise BlockNpvHeadError(f"physical {name} is invalid")
        elif self.physical_ensemble_version or self.physical_blend_provenance_hash:
            raise BlockNpvHeadError("zero physical weight must not pin blend inputs")
        fingerprint = self._fingerprint()
        if self.version and self.version != fingerprint:
            raise BlockNpvHeadError("block head fingerprint differs")
        self.version = fingerprint

    def predict_vectors_raw(self, vectors: Tensor) -> Tensor:
        if vectors.ndim != 2 or vectors.shape[1:] != self.feature_mean.shape:
            raise BlockNpvHeadError("block prediction feature width differs")
        standardized = (
            vectors.to(torch.float64) - self.feature_mean
        ) / self.feature_scale
        normalized = (
            _block_kernel(
                standardized,
                self.centers,
                blocks=self.blocks,
                active_widths=self.active_widths,
                weights=self.block_weights,
                mode=self.mode,
            )
            @ self.dual
        )
        return self.target_mean_rub + self.target_scale_rub * normalized

    def predict_vectors(self, vectors: Tensor) -> Tensor:
        return (
            self.calibration_intercept_rub
            + self.calibration_slope * self.predict_vectors_raw(vectors)
        )

    def predict_vector(self, vector: Tensor) -> float:
        return float(self.predict_vectors(vector.unsqueeze(0))[0])

    def predict(self, candidate: SurrogateInput) -> float:
        if candidate.static_feature_names != self.static_feature_names:
            raise BlockNpvHeadError("block head static feature axis differs")
        x, well_index = build_features(candidate, self.wells, scenario_context=False)
        vector = scenario_feature_vector(
            x,
            well_index,
            n_wells=len(self.wells),
            feature_set="economic",
        )
        return self.predict_vector(vector)

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        metadata = {
                    "format": FORMAT,
                    "wells": self.wells,
                    "static_feature_names": self.static_feature_names,
                    "blocks": self.blocks,
                    "active_widths": self.active_widths,
                    "block_weights": self.block_weights,
                    "mode": self.mode,
                    "ridge": self.ridge,
                    "target_mean_rub": self.target_mean_rub,
                    "target_scale_rub": self.target_scale_rub,
                    "dataset_hash": self.dataset_hash,
                    "target_provenance_hash": self.target_provenance_hash,
                    "feature_provenance_hash": self.feature_provenance_hash,
                    "feature_context_sha256": self.feature_context_sha256,
                    "implementation_hash": self.implementation_hash,
                    "calibration_slope": self.calibration_slope,
                    "calibration_intercept_rub": self.calibration_intercept_rub,
                }
        if self.physical_npv_weight > 0.0:
            metadata.update(
                {
                    "physical_npv_weight": self.physical_npv_weight,
                    "physical_ensemble_version": self.physical_ensemble_version,
                    "physical_blend_provenance_hash": (
                        self.physical_blend_provenance_hash
                    ),
                }
            )
        digest.update(
            json.dumps(
                metadata,
                sort_keys=True,
            ).encode()
        )
        for tensor in (
            self.feature_mean,
            self.feature_scale,
            self.centers,
            self.dual,
        ):
            digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
        return digest.hexdigest()

    def save(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
                "format": FORMAT,
                "wells": self.wells,
                "static_feature_names": self.static_feature_names,
                "blocks": self.blocks,
                "active_widths": self.active_widths,
                "block_weights": self.block_weights,
                "mode": self.mode,
                "ridge": self.ridge,
                "feature_mean": self.feature_mean,
                "feature_scale": self.feature_scale,
                "centers": self.centers,
                "dual": self.dual,
                "target_mean_rub": self.target_mean_rub,
                "target_scale_rub": self.target_scale_rub,
                "dataset_hash": self.dataset_hash,
                "target_provenance_hash": self.target_provenance_hash,
                "feature_provenance_hash": self.feature_provenance_hash,
                "feature_context_sha256": self.feature_context_sha256,
                "implementation_hash": self.implementation_hash,
                "calibration_slope": self.calibration_slope,
                "calibration_intercept_rub": self.calibration_intercept_rub,
                "version": self.version,
            }
        if self.physical_npv_weight > 0.0:
            payload.update(
                {
                    "physical_npv_weight": self.physical_npv_weight,
                    "physical_ensemble_version": self.physical_ensemble_version,
                    "physical_blend_provenance_hash": (
                        self.physical_blend_provenance_hash
                    ),
                }
            )
        torch.save(payload, destination)
        return destination

    @classmethod
    def load(cls, path: Path | str) -> BlockKernelNpvHead:
        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        if payload.get("format") != FORMAT:
            raise BlockNpvHeadError("unsupported block NPV head artifact")
        return cls(
            wells=tuple(payload["wells"]),
            static_feature_names=tuple(payload["static_feature_names"]),
            blocks=tuple(tuple(item) for item in payload["blocks"]),
            active_widths=tuple(int(item) for item in payload["active_widths"]),
            block_weights=tuple(float(item) for item in payload["block_weights"]),
            mode=payload["mode"],
            ridge=float(payload["ridge"]),
            feature_mean=payload["feature_mean"].to(torch.float64),
            feature_scale=payload["feature_scale"].to(torch.float64),
            centers=payload["centers"].to(torch.float64),
            dual=payload["dual"].to(torch.float64),
            target_mean_rub=float(payload["target_mean_rub"]),
            target_scale_rub=float(payload["target_scale_rub"]),
            dataset_hash=str(payload["dataset_hash"]),
            target_provenance_hash=str(payload["target_provenance_hash"]),
            feature_provenance_hash=str(payload["feature_provenance_hash"]),
            feature_context_sha256=str(payload["feature_context_sha256"]),
            implementation_hash=str(payload["implementation_hash"]),
            calibration_slope=float(payload["calibration_slope"]),
            calibration_intercept_rub=float(payload["calibration_intercept_rub"]),
            physical_npv_weight=float(payload.get("physical_npv_weight", 0.0)),
            physical_ensemble_version=str(
                payload.get("physical_ensemble_version", "")
            ),
            physical_blend_provenance_hash=str(
                payload.get("physical_blend_provenance_hash", "")
            ),
            version=str(payload["version"]),
        )


__all__ = [
    "BlockKernelNpvHead",
]
