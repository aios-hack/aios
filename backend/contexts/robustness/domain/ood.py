
from __future__ import annotations

from backend.contexts.robustness.domain.errors import (
    OodError,
)

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from backend.contexts.surrogate.domain.features import SurrogateInput, WellStepFeatures
from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput

NUMERIC_FEATURES: tuple[str, ...] = (
    "setpoint_m3_per_day",
    "effective_target_rate_m3_per_day",
    "cumulative_target_liquid_m3",
    "cumulative_target_injection_m3",
    "cumulative_neighbor_injection_m3",
    "current_neighbor_injection_m3_per_day",
    "event_count",
    "fixed_event_count",
)

CATEGORICAL_FEATURES: tuple[str, ...] = (
    "availability",
    "role",
    "operating_status",
)


@dataclass(frozen=True, slots=True)
class FeatureRange:
    name: str
    low: float
    high: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.low) or not math.isfinite(self.high):
            raise OodError(f"{self.name}: bounds are not finite ({self.low}, {self.high})")
        if self.high < self.low:
            raise OodError(f"{self.name}: high {self.high} < low {self.low}")

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def degenerate(self) -> bool:
        return self.width == 0.0

    def exceedance(self, value: float) -> float:
        if not math.isfinite(value):
            return math.inf
        if self.low <= value <= self.high:
            return 0.0
        if self.degenerate:
            return math.inf
        distance = self.low - value if value < self.low else value - self.high
        return distance / self.width


@dataclass(frozen=True, slots=True)
class TrainingDomain:
    ranges: tuple[FeatureRange, ...]
    categories: tuple[tuple[str, frozenset[str]], ...]
    static_feature_names: tuple[str, ...]
    n_nodes: int
    schedule_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.n_nodes < 1:
            raise OodError("the training domain cannot be built from an empty sample")

    def range_of(self, name: str) -> FeatureRange:
        for item in self.ranges:
            if item.name == name:
                return item
        raise OodError(f"feature {name!r} is not in the training domain")

    def categories_of(self, name: str) -> frozenset[str]:
        for key, values in self.categories:
            if key == name:
                return values
        raise OodError(f"categorical feature {name!r} is not in the training domain")


@dataclass(frozen=True, slots=True)
class Exceedance:
    feature: str
    well: str
    control_step: int
    value: float
    low: float
    high: float
    score: float


@dataclass(frozen=True, slots=True)
class OodScore:
    score: float
    exceedances: tuple[Exceedance, ...]
    n_nodes: int

    @property
    def worst(self) -> Exceedance | None:
        return self.exceedances[0] if self.exceedances else None

    def inside(self, tau: float) -> bool:
        if tau < 0.0:
            raise OodError(f"the trust-region threshold τ={tau} is negative")
        return self.score <= tau


@dataclass(frozen=True, slots=True)
class ScoredPrediction:
    output: RawModelOutput
    ood: OodScore


def _numeric(node: WellStepFeatures, name: str) -> float:
    return float(getattr(node, name))


def _categorical(node: WellStepFeatures, name: str) -> str:
    return getattr(node, name).value


def _static_names(inputs: Sequence[SurrogateInput]) -> tuple[str, ...]:
    names = inputs[0].static_feature_names
    for other in inputs[1:]:
        if other.static_feature_names != names:
            raise OodError(
                "the set of static features diverged between schedules: "
                f"{names} against {other.static_feature_names}"
            )
    return names


def fit_domain(inputs: Sequence[SurrogateInput]) -> TrainingDomain:
    if not inputs:
        raise OodError("the training domain cannot be built from an empty sample")

    static_names = _static_names(inputs)
    lows: dict[str, float] = {}
    highs: dict[str, float] = {}
    seen: dict[str, set[str]] = {name: set() for name in CATEGORICAL_FEATURES}
    n_nodes = 0

    for item in inputs:
        for node in item.nodes:
            n_nodes += 1
            if len(node.static_values) != len(static_names):
                raise OodError(
                    f"well {node.well}: {len(node.static_values)} static values "
                    f"against {len(static_names)} names"
                )
            for name in NUMERIC_FEATURES:
                value = _numeric(node, name)
                if not math.isfinite(value):
                    raise OodError(f"well {node.well}: {name}={value!r} is not finite")
                lows[name] = value if name not in lows else min(lows[name], value)
                highs[name] = value if name not in highs else max(highs[name], value)
            for index, name in enumerate(static_names):
                key = f"static:{name}"
                value = float(node.static_values[index])
                if not math.isfinite(value):
                    raise OodError(f"well {node.well}: {key}={value!r} is not finite")
                lows[key] = value if key not in lows else min(lows[key], value)
                highs[key] = value if key not in highs else max(highs[key], value)
            for name in CATEGORICAL_FEATURES:
                seen[name].add(_categorical(node, name))

    if n_nodes == 0:
        raise OodError("the dataset inputs contain no nodes")

    ranges = tuple(
        FeatureRange(name=name, low=lows[name], high=highs[name])
        for name in sorted(lows)
    )
    categories = tuple(
        (name, frozenset(values)) for name, values in sorted(seen.items())
    )
    return TrainingDomain(
        ranges=ranges,
        categories=categories,
        static_feature_names=static_names,
        n_nodes=n_nodes,
        schedule_hashes=tuple(item.canonical_schedule_hash for item in inputs),
    )


def score(candidate: SurrogateInput, domain: TrainingDomain) -> OodScore:
    if candidate.static_feature_names != domain.static_feature_names:
        raise OodError(
            "the candidate static feature set does not match the training one: "
            f"{candidate.static_feature_names} against {domain.static_feature_names}"
        )

    exceedances: list[Exceedance] = []
    n_nodes = 0

    for node in candidate.nodes:
        n_nodes += 1
        for name in NUMERIC_FEATURES:
            interval = domain.range_of(name)
            value = _numeric(node, name)
            amount = interval.exceedance(value)
            if amount > 0.0:
                exceedances.append(
                    Exceedance(
                        feature=name,
                        well=node.well,
                        control_step=node.control_step,
                        value=value,
                        low=interval.low,
                        high=interval.high,
                        score=amount,
                    )
                )
        for index, name in enumerate(domain.static_feature_names):
            key = f"static:{name}"
            interval = domain.range_of(key)
            value = float(node.static_values[index])
            amount = interval.exceedance(value)
            if amount > 0.0:
                exceedances.append(
                    Exceedance(
                        feature=key,
                        well=node.well,
                        control_step=node.control_step,
                        value=value,
                        low=interval.low,
                        high=interval.high,
                        score=amount,
                    )
                )
        for name in CATEGORICAL_FEATURES:
            allowed = domain.categories_of(name)
            value = _categorical(node, name)
            if value not in allowed:
                exceedances.append(
                    Exceedance(
                        feature=name,
                        well=node.well,
                        control_step=node.control_step,
                        value=math.nan,
                        low=math.nan,
                        high=math.nan,
                        score=math.inf,
                    )
                )

    if n_nodes == 0:
        raise OodError("the candidate contains no nodes")

    exceedances.sort(key=lambda item: (-item.score, item.control_step, item.well))
    worst = exceedances[0].score if exceedances else 0.0
    return OodScore(score=worst, exceedances=tuple(exceedances), n_nodes=n_nodes)


def predict_with_score(
    output: RawModelOutput, candidate: SurrogateInput, domain: TrainingDomain
) -> ScoredPrediction:
    return ScoredPrediction(output=output, ood=score(candidate, domain))


def worst_offenders(assessment: OodScore, limit: int = 5) -> tuple[Exceedance, ...]:
    if limit < 1:
        raise OodError(f"limit={limit} < 1")
    return assessment.exceedances[:limit]


def domain_of_inputs(inputs: Iterable[SurrogateInput]) -> TrainingDomain:
    return fit_domain(tuple(inputs))
