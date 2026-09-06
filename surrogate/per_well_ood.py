"""Train-only per-well input ranges complementing the global OOD domain."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path

from surrogate.features import SurrogateInput
from surrogate.ood import Exceedance, NUMERIC_FEATURES, OodScore

FORMAT = "aios.surrogate-per-well-input-domain.v1"


class PerWellDomainError(ValueError):
    pass


def _float32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


@dataclass(frozen=True, slots=True)
class PerWellInputDomain:
    dataset_hash: str
    wells: tuple[str, ...]
    feature_names: tuple[str, ...]
    lows_log1p: tuple[tuple[float, ...], ...]
    highs_log1p: tuple[tuple[float, ...], ...]
    threshold: float
    n_fit_scenarios: int
    threshold_quantile: float
    validation_scenario_count: int
    validation_inside_count: int
    version: str = ""

    def __post_init__(self) -> None:
        width = len(self.feature_names)
        if self.feature_names != NUMERIC_FEATURES:
            raise PerWellDomainError("per-well feature order differs from model input")
        if not self.wells or len(set(self.wells)) != len(self.wells):
            raise PerWellDomainError("per-well domain has invalid well axis")
        if (
            len(self.lows_log1p) != len(self.wells)
            or len(self.highs_log1p) != len(self.wells)
            or any(len(row) != width for row in self.lows_log1p)
            or any(len(row) != width for row in self.highs_log1p)
        ):
            raise PerWellDomainError("per-well range axes differ")
        for lows, highs in zip(self.lows_log1p, self.highs_log1p, strict=True):
            for low, high in zip(lows, highs, strict=True):
                if not math.isfinite(low) or not math.isfinite(high) or high < low:
                    raise PerWellDomainError("invalid per-well range")
        if not math.isfinite(self.threshold) or self.threshold < 0.0:
            raise PerWellDomainError("per-well threshold must be finite and nonnegative")
        if not 0.0 < self.threshold_quantile < 1.0:
            raise PerWellDomainError("threshold quantile must lie in (0, 1)")
        if (
            self.n_fit_scenarios < 1
            or self.validation_scenario_count < 2
            or not 0 <= self.validation_inside_count <= self.validation_scenario_count
        ):
            raise PerWellDomainError("invalid fit/validation counts")
        expected = self._fingerprint()
        if self.version and self.version != expected:
            raise PerWellDomainError("per-well domain fingerprint differs")
        object.__setattr__(self, "version", expected)

    def _fingerprint(self) -> str:
        payload = {
            "format": FORMAT,
            "dataset_hash": self.dataset_hash,
            "wells": self.wells,
            "feature_names": self.feature_names,
            "lows_log1p": self.lows_log1p,
            "highs_log1p": self.highs_log1p,
            "threshold": self.threshold,
            "n_fit_scenarios": self.n_fit_scenarios,
            "threshold_quantile": self.threshold_quantile,
            "validation_scenario_count": self.validation_scenario_count,
            "validation_inside_count": self.validation_inside_count,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def score(self, candidate: SurrogateInput) -> OodScore:
        if candidate.wells != self.wells:
            raise PerWellDomainError("candidate well axis differs from per-well domain")
        well_index = {well: index for index, well in enumerate(self.wells)}
        exceedances = []
        for node in candidate.nodes:
            index = well_index[node.well]
            lows = self.lows_log1p[index]
            highs = self.highs_log1p[index]
            for feature_index, name in enumerate(self.feature_names):
                raw = float(getattr(node, name))
                if raw < 0.0 or not math.isfinite(raw):
                    value = math.inf
                else:
                    value = _float32(math.log1p(raw))
                low = lows[feature_index]
                high = highs[feature_index]
                tolerance = 1.0e-6 * max(1.0, abs(low), abs(high))
                width = high - low
                if low - tolerance <= value <= high + tolerance:
                    continue
                if not math.isfinite(value) or width <= 1.0e-7:
                    amount = math.inf
                else:
                    distance = low - value if value < low else value - high
                    amount = max(0.0, distance - tolerance) / width
                exceedances.append(
                    Exceedance(
                        feature=f"per_well:{name}",
                        well=node.well,
                        control_step=node.control_step,
                        value=raw,
                        low=math.expm1(low),
                        high=math.expm1(high),
                        score=amount,
                    )
                )
        exceedances.sort(key=lambda item: (-item.score, item.control_step, item.well))
        return OodScore(
            score=exceedances[0].score if exceedances else 0.0,
            exceedances=tuple(exceedances),
            n_nodes=len(candidate.nodes),
        )

    def save(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": FORMAT,
            "dataset_hash": self.dataset_hash,
            "wells": self.wells,
            "feature_names": self.feature_names,
            "lows_log1p": self.lows_log1p,
            "highs_log1p": self.highs_log1p,
            "threshold": self.threshold,
            "fit_bucket": "train",
            "n_fit_scenarios": self.n_fit_scenarios,
            "threshold_bucket": "validation",
            "threshold_quantile": self.threshold_quantile,
            "validation_scenario_count": self.validation_scenario_count,
            "validation_inside_count": self.validation_inside_count,
            "historical_test_read": False,
            "blind_response_read": False,
            "version": self.version,
        }
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    @classmethod
    def load(cls, path: Path | str) -> "PerWellInputDomain":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format") != FORMAT:
            raise PerWellDomainError("unsupported per-well domain format")
        if (
            payload.get("fit_bucket") != "train"
            or payload.get("threshold_bucket") != "validation"
            or payload.get("historical_test_read") is not False
            or payload.get("blind_response_read") is not False
        ):
            raise PerWellDomainError("per-well domain provenance is unsafe")
        return cls(
            dataset_hash=str(payload["dataset_hash"]),
            wells=tuple(payload["wells"]),
            feature_names=tuple(payload["feature_names"]),
            lows_log1p=tuple(tuple(row) for row in payload["lows_log1p"]),
            highs_log1p=tuple(tuple(row) for row in payload["highs_log1p"]),
            threshold=float(payload["threshold"]),
            n_fit_scenarios=int(payload["n_fit_scenarios"]),
            threshold_quantile=float(payload["threshold_quantile"]),
            validation_scenario_count=int(payload["validation_scenario_count"]),
            validation_inside_count=int(payload["validation_inside_count"]),
            version=str(payload["version"]),
        )
