"""Direct scenario-level NPV head over schedule-only surrogate features."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import torch
from torch import Tensor

from contracts import N_INTERVALS

from .features import SurrogateInput
from .model import _features

FORMAT = "aios.surrogate-scenario-npv-head.v1"
BASE_FEATURES = 21
TEMPORAL_BINS = 28
WELL_TEMPORAL_FEATURES = 6
ECONOMIC_WELL_FEATURES = 14
ECONOMIC_AGGREGATIONS = 4
KernelName = Literal["linear", "poly2", "rbf"]
FeatureSet = Literal["global", "temporal", "full", "economic", "well_temporal"]
FEATURE_PROVENANCE_FILES = (
    "contracts/schedule.py",
    "surrogate/features.py",
    "surrogate/model.py",
    "surrogate/npv_head.py",
)

# Хеш берётся по целым файлам, поэтому меняется от любой правки в них — вплоть
# до комментария, — хотя признаки головы собирает единственная импортируемая
# отсюда функция `model._features`. `surrogate/model.py` — 1449 строк под
# активной разработкой, так что ложное срабатывание неизбежно и повторяемо.
# Список ниже — тот же приём, что `LEGACY_IMPLEMENTATION_HASHES` в
# `npv_block_head.py`: явный, проверяемый, с указанием, какая правка покрыта.
#
# Запись добавляется только после доказательства, что признаковая поверхность
# не изменилась. Способ доказательства — сравнить исходники функций, а не
# файлы:
#
#     ast.get_source_segment для `_features` и `_scenario_summary`
#     до и после правки обязан совпасть байт в байт.
#
# 0071d65d — состояние до предела «нефть не больше жидкости в объёме»
# (`predict`, `_scenario_money`, `_proxy_value`). Сравнение показало, что
# изменились ровно эти три функции; `_features` и `_scenario_summary`
# идентичны, то есть вход головы прежний.
LEGACY_FEATURE_PROVENANCE_HASHES = {
    "0071d65d57e16ada366585177aadd2235074022d094cc156ab72b00b22d6ad7c",
}


class ScenarioNpvHeadError(ValueError):
    pass


def feature_implementation_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for relative in FEATURE_PROVENANCE_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()


def _economic_event_vector(grid: Tensor) -> Tensor:
    """Exact schedule-state events relevant to event CAPEX/OPEX and timing."""

    n_wells = grid.shape[1]
    available = grid[:, :, 15] > 0.5
    opened = grid[:, :, 19] > 0.5
    producer = available & opened & (grid[:, :, 17] > 0.5)
    injector = available & opened & (grid[:, :, 18] > 0.5)
    state = torch.where(
        producer,
        torch.ones_like(grid[:, :, 0], dtype=torch.long),
        torch.where(
            injector,
            torch.full_like(grid[:, :, 0], 2, dtype=torch.long),
            torch.zeros_like(grid[:, :, 0], dtype=torch.long),
        ),
    )
    per_well = []
    for well in range(n_wells):
        values = state[:, well].tolist()
        last_active = 0
        previous = 0
        seen_active = False
        launches = restarts = conversions = reverse_conversions = shutdowns = 0
        post_active_shut = 0
        first_active = N_INTERVALS - 1
        first_injection = N_INTERVALS - 1
        for step, current in enumerate(values):
            if current == 0:
                if seen_active:
                    post_active_shut += 1
                if previous:
                    shutdowns += 1
            else:
                if not seen_active:
                    launches += 1
                    first_active = step
                elif current != last_active:
                    if last_active == 1 and current == 2:
                        conversions += 1
                    elif last_active == 2 and current == 1:
                        reverse_conversions += 1
                elif previous == 0:
                    restarts += 1
                if current == 2 and first_injection == N_INTERVALS - 1:
                    first_injection = step
                seen_active = True
                last_active = current
            previous = current
        prod_mask = producer[:, well]
        inj_mask = injector[:, well]
        effective = grid[:, well, 1]
        zero = effective.new_zeros(())
        per_well.append(
            torch.stack(
                (
                    prod_mask.to(grid.dtype).mean(),
                    inj_mask.to(grid.dtype).mean(),
                    grid.new_tensor(post_active_shut / N_INTERVALS),
                    grid.new_tensor(float(launches)),
                    grid.new_tensor(float(restarts)),
                    grid.new_tensor(float(conversions)),
                    grid.new_tensor(float(reverse_conversions)),
                    grid.new_tensor(float(shutdowns)),
                    grid.new_tensor(first_active / (N_INTERVALS - 1)),
                    grid.new_tensor(first_injection / (N_INTERVALS - 1)),
                    grid[-1, well, 2],
                    grid[-1, well, 3],
                    effective[prod_mask].amax() if bool(prod_mask.any()) else zero,
                    effective[inj_mask].amax() if bool(inj_mask.any()) else zero,
                )
            )
        )
    matrix = torch.stack(per_well)
    if matrix.shape != (n_wells, ECONOMIC_WELL_FEATURES):
        raise ScenarioNpvHeadError("economic event feature width differs")
    aggregate = torch.cat(
        (
            matrix.mean(dim=0),
            matrix.std(dim=0, unbiased=False),
            matrix.amax(dim=0),
            matrix.sum(dim=0),
        )
    )
    return torch.cat((aggregate, matrix.reshape(-1)))


def scenario_feature_vector(
    x: Tensor,
    well_index: Tensor,
    *,
    n_wells: int,
    feature_set: FeatureSet = "full",
) -> Tensor:
    """Collapse one complete schedule tensor into a scenario representation."""

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
    grid = torch.empty(
        N_INTERVALS * n_wells,
        BASE_FEATURES,
        dtype=torch.float64,
    )
    grid[flat_index] = base
    grid = grid.reshape(N_INTERVALS, n_wells, BASE_FEATURES)

    rows = grid.reshape(-1, BASE_FEATURES)
    global_features = torch.cat(
        (
            rows.mean(dim=0),
            rows.std(dim=0, unbiased=False),
            rows.amin(dim=0),
            rows.amax(dim=0),
        )
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

    if feature_set not in {"full", "economic", "well_temporal"}:
        raise ScenarioNpvHeadError(f"неизвестный feature_set={feature_set!r}")
    controls = grid[:, :, :8]
    by_well = torch.cat(
        (
            controls.mean(dim=0),
            controls.std(dim=0, unbiased=False),
        ),
        dim=1,
    ).reshape(-1)
    full = torch.cat((global_features, temporal, by_well))
    if feature_set == "full":
        return full
    if feature_set == "economic":
        return torch.cat((full, _economic_event_vector(grid)))

    well_temporal = grid.reshape(
        TEMPORAL_BINS,
        bin_width,
        n_wells,
        BASE_FEATURES,
    ).mean(dim=1)[:, :, :WELL_TEMPORAL_FEATURES]
    return torch.cat((full, well_temporal.reshape(-1)))


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

    def __post_init__(self) -> None:
        if len(self.static_feature_names) != 3:
            raise ScenarioNpvHeadError("NPV head v1 ожидает три статических признака")
        if self.kernel not in {"linear", "poly2", "rbf"}:
            raise ScenarioNpvHeadError(f"неизвестный kernel={self.kernel!r}")
        if self.feature_set not in {
            "global",
            "temporal",
            "full",
            "economic",
            "well_temporal",
        }:
            raise ScenarioNpvHeadError(f"неизвестный feature_set={self.feature_set!r}")
        if self.gamma <= 0.0 or not math.isfinite(self.gamma):
            raise ScenarioNpvHeadError("gamma должна быть конечной и положительной")
        if self.target_scale_rub <= 0.0:
            raise ScenarioNpvHeadError("target scale должна быть положительной")
        if self.target_provenance_hash and len(self.target_provenance_hash) != 64:
            raise ScenarioNpvHeadError("target provenance hash должен иметь 64 символа")
        if self.target_provenance_hash and not self.feature_provenance_hash:
            raise ScenarioNpvHeadError(
                "corrected target head обязан фиксировать feature provenance"
            )
        if self.target_provenance_hash and not self.feature_context_sha256:
            raise ScenarioNpvHeadError(
                "corrected target head обязан фиксировать feature context"
            )
        if self.feature_context_sha256 and (
            len(self.feature_context_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.feature_context_sha256
            )
        ):
            raise ScenarioNpvHeadError("feature context SHA-256 задан неверно")
        if self.feature_provenance_hash and (
            len(self.feature_provenance_hash) != 64
            or self.feature_provenance_hash
            not in {feature_implementation_hash(), *LEGACY_FEATURE_PROVENANCE_HASHES}
        ):
            raise ScenarioNpvHeadError("feature provenance hash не совпадает")
        if not math.isfinite(self.calibration_slope) or self.calibration_slope <= 0.0:
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
        self.version = self.version or self._fingerprint()

    def predict_vector(self, vector: Tensor) -> float:
        if vector.shape != self.feature_mean.shape:
            raise ScenarioNpvHeadError(
                f"feature vector {vector.shape} != {self.feature_mean.shape}"
            )
        return float(self.predict_vectors(vector.unsqueeze(0))[0])

    def predict_vectors(self, vectors: Tensor) -> Tensor:
        raw = self.predict_vectors_raw(vectors)
        return self.calibration_intercept_rub + self.calibration_slope * raw

    def predict_vectors_raw(self, vectors: Tensor) -> Tensor:
        if vectors.ndim != 2 or vectors.shape[1:] != self.feature_mean.shape:
            raise ScenarioNpvHeadError(
                f"feature vectors {vectors.shape} несовместимы с "
                f"{self.feature_mean.shape}"
            )
        standardized = (
            vectors.to(torch.float64) - self.feature_mean
        ) / self.feature_scale
        normalized = (
            _kernel(standardized, self.centers, self.kernel, self.gamma) @ self.dual
        )
        return self.target_mean_rub + self.target_scale_rub * normalized

    def predict(self, candidate: SurrogateInput) -> float:
        if candidate.static_feature_names != self.static_feature_names:
            raise ScenarioNpvHeadError("статика кандидата не совпадает с NPV head")
        x, well_index = _features(candidate, self.wells, scenario_context=False)
        vector = scenario_feature_vector(
            x,
            well_index,
            n_wells=len(self.wells),
            feature_set=self.feature_set,
        )
        return self.predict_vector(vector)

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
        torch.save(
            {
                "format": FORMAT,
                "wells": self.wells,
                "static_feature_names": self.static_feature_names,
                "feature_set": self.feature_set,
                "kernel": self.kernel,
                "gamma": self.gamma,
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
                "calibration_slope": self.calibration_slope,
                "calibration_intercept_rub": self.calibration_intercept_rub,
                "version": self.version,
            },
            destination,
        )
        return destination

    @classmethod
    def load(cls, path: Path | str) -> ScenarioNpvHead:
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
            target_provenance_hash=str(payload.get("target_provenance_hash", "")),
            feature_provenance_hash=str(payload.get("feature_provenance_hash", "")),
            feature_context_sha256=str(payload.get("feature_context_sha256", "")),
            calibration_slope=float(payload.get("calibration_slope", 1.0)),
            calibration_intercept_rub=float(
                payload.get("calibration_intercept_rub", 0.0)
            ),
            version=str(payload["version"]),
        )
        if head._fingerprint() != head.version:
            raise ScenarioNpvHeadError("NPV head fingerprint не совпадает")
        return head
