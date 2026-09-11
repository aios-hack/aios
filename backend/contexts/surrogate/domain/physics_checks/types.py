from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.surrogate.domain.errors import PhysicsCheckError
from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput


FORMAT = "aios.surrogate-physics-report.v1"

DEFAULT_OIL_DENSITY_T_PER_M3 = 0.9131

DEFAULT_ZERO_TOLERANCE = 1e-3

DEFAULT_WATERCUT_TOLERANCE = 1e-3

DEFAULT_RELATIVE_TOLERANCE = 5e-3

DEFAULT_MAX_EXAMPLES_PER_INVARIANT = 8


class Invariant(Enum):
    NON_NEGATIVE = "NON_NEGATIVE"
    WATERCUT_RANGE = "WATERCUT_RANGE"
    CUMULATIVE_MONOTONIC = "CUMULATIVE_MONOTONIC"
    SHUT_WELL_FLOW = "SHUT_WELL_FLOW"
    BHP_LIMIT = "BHP_LIMIT"
    INJECTION_RESPONSE = "INJECTION_RESPONSE"
    MATERIAL_BALANCE = "MATERIAL_BALANCE"


class Severity(Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


_SEVERITY: Mapping[Invariant, Severity] = {
    Invariant.NON_NEGATIVE: Severity.BLOCKING,
    Invariant.WATERCUT_RANGE: Severity.BLOCKING,
    Invariant.CUMULATIVE_MONOTONIC: Severity.BLOCKING,
    Invariant.SHUT_WELL_FLOW: Severity.BLOCKING,
    Invariant.BHP_LIMIT: Severity.WARNING,
    Invariant.INJECTION_RESPONSE: Severity.BLOCKING,
    Invariant.MATERIAL_BALANCE: Severity.BLOCKING,
}


def severity_of(invariant: Invariant | str) -> Severity:
    return _SEVERITY[Invariant(invariant) if isinstance(invariant, str) else invariant]


_SINGLE_PREDICTION_INVARIANTS: tuple[Invariant, ...] = (
    Invariant.NON_NEGATIVE,
    Invariant.WATERCUT_RANGE,
    Invariant.CUMULATIVE_MONOTONIC,
    Invariant.SHUT_WELL_FLOW,
    Invariant.BHP_LIMIT,
)
_DIFFERENTIAL_INVARIANTS: tuple[Invariant, ...] = (
    Invariant.INJECTION_RESPONSE,
    Invariant.MATERIAL_BALANCE,
)

_RATE_CHANNELS: tuple[str, ...] = ("liquid_rate", "injection_rate")
_VOLUME_CHANNELS: tuple[str, ...] = (
    "oil_mass_delta",
    "liquid_volume_delta",
    "injection_volume_delta",
)

_BHP_ARG_INDEX: Mapping[str, int] = {"WCONPROD": 7, "WCONINJE": 5}


@dataclass(frozen=True, slots=True)
class PhysicsFlag:
    invariant: Invariant
    severity: Severity
    well: str
    observed: float
    limit: float
    detail: str
    control_step: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "invariant": self.invariant.value,
            "severity": self.severity.value,
            "well": self.well,
            "control_step": self.control_step,
            "observed": self.observed,
            "limit": self.limit,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class PhysicsReport:
    counts: Mapping[str, int]
    examples: tuple[PhysicsFlag, ...]
    evaluated: tuple[Invariant, ...]
    skipped: Mapping[str, str]
    n_nodes: int
    n_wells: int
    format: str = FORMAT

    def __post_init__(self) -> None:
        known = {invariant.value for invariant in Invariant}
        unknown = (set(self.counts) | set(self.skipped)) - known
        if unknown:
            raise PhysicsCheckError(f"unknown invariants in the report: {sorted(unknown)}")
        overlap = {invariant.value for invariant in self.evaluated} & set(self.skipped)
        if overlap:
            raise PhysicsCheckError(
                f"an invariant is simultaneously satisfied and skipped: {sorted(overlap)}"
            )

    @property
    def n_flags(self) -> int:
        return sum(self.counts.values())

    @property
    def blocking_count(self) -> int:
        return sum(
            count
            for name, count in self.counts.items()
            if _SEVERITY[Invariant(name)] is Severity.BLOCKING
        )

    @property
    def warning_count(self) -> int:
        return self.n_flags - self.blocking_count

    @property
    def complete(self) -> bool:
        return len(self.evaluated) == len(Invariant)

    @property
    def admissible(self) -> bool:
        return self.complete and self.blocking_count == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "n_nodes": self.n_nodes,
            "n_wells": self.n_wells,
            "n_flags": self.n_flags,
            "blocking_count": self.blocking_count,
            "warning_count": self.warning_count,
            "complete": self.complete,
            "admissible": self.admissible,
            "counts": dict(sorted(self.counts.items())),
            "evaluated": sorted(invariant.value for invariant in self.evaluated),
            "skipped": dict(sorted(self.skipped.items())),
            "examples": [flag.as_dict() for flag in self.examples],
        }


@dataclass(frozen=True, slots=True)
class BhpLimits:
    producer_floor: Mapping[str, float]
    injector_ceiling: Mapping[str, float]
    producer_default: float | None
    injector_default: float | None

    @classmethod
    def from_schedule(cls, schedule: Schedule) -> "BhpLimits":
        floors: dict[str, float] = {}
        ceilings: dict[str, float] = {}
        for event in schedule.fixed_deck_events:
            index = _BHP_ARG_INDEX.get(event.operator)
            if index is None or index >= len(event.raw_args):
                continue
            value = _deck_float(event.raw_args[index])
            if value is None:
                continue
            target = floors if event.operator == "WCONPROD" else ceilings
            target[event.well] = value
        return cls(
            producer_floor=floors,
            injector_ceiling=ceilings,
            producer_default=_unique_value(floors.values()),
            injector_default=_unique_value(ceilings.values()),
        )

    def floor_for(self, well: str) -> float | None:
        return self.producer_floor.get(well, self.producer_default)

    def ceiling_for(self, well: str) -> float | None:
        return self.injector_ceiling.get(well, self.injector_default)

    @property
    def usable(self) -> bool:
        return self.producer_default is not None or self.injector_default is not None


def _deck_float(token: str) -> float | None:
    text = token.strip().strip("'\"")
    if not text or text.endswith("*"):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _unique_value(values: Iterable[float]) -> float | None:
    distinct = {round(value, 9) for value in values}
    return next(iter(distinct)) if len(distinct) == 1 else None


class _FlagSink:
    def __init__(self, max_examples: int) -> None:
        if max_examples < 1:
            raise PhysicsCheckError("max_examples must be positive")
        self._max_examples = max_examples
        self._counts: Counter[str] = Counter()
        self._examples: list[PhysicsFlag] = []

    def add(
        self,
        invariant: Invariant,
        *,
        well: str,
        observed: float,
        limit: float,
        detail: str,
        control_step: int | None = None,
    ) -> None:
        name = invariant.value
        self._counts[name] += 1
        if self._counts[name] <= self._max_examples:
            self._examples.append(
                PhysicsFlag(
                    invariant=invariant,
                    severity=_SEVERITY[invariant],
                    well=well,
                    observed=observed,
                    limit=limit,
                    detail=detail,
                    control_step=control_step,
                )
            )

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    @property
    def examples(self) -> tuple[PhysicsFlag, ...]:
        return tuple(self._examples)


def _require_same_axis(raw: RawModelOutput, schedule: Schedule) -> None:
    if set(raw.wells) != set(schedule.meta.wells):
        raise PhysicsCheckError(
            "the wells axis of the forecast does not match the schedule: "
            f"{len(raw.wells)} against {len(schedule.meta.wells)}"
        )


__all__ = [
    "BhpLimits",
    "DEFAULT_MAX_EXAMPLES_PER_INVARIANT",
    "DEFAULT_OIL_DENSITY_T_PER_M3",
    "DEFAULT_RELATIVE_TOLERANCE",
    "DEFAULT_WATERCUT_TOLERANCE",
    "DEFAULT_ZERO_TOLERANCE",
    "FORMAT",
    "Invariant",
    "PhysicsFlag",
    "PhysicsReport",
    "Severity",
    "severity_of",
]
