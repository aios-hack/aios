
from __future__ import annotations

from backend.contexts.surrogate.domain.errors import (
    PhysicsCheckError,
)

import math
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from backend.contexts.simulation.infrastructure.response_loader import _build_well_timelines
from backend.core.contracts import EventKind, Lambda, OperatingStatus, Role, Schedule

from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput, RawWellStepPrediction
from backend.contexts.surrogate.domain.schedule_roles import build_role_timelines

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
            raise PhysicsCheckError(f"неизвестные инварианты в отчёте: {sorted(unknown)}")
        overlap = {invariant.value for invariant in self.evaluated} & set(self.skipped)
        if overlap:
            raise PhysicsCheckError(
                f"инвариант одновременно выполнен и пропущен: {sorted(overlap)}"
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
            raise PhysicsCheckError("max_examples должен быть положительным")
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


def check_prediction(
    raw: RawModelOutput,
    *,
    schedule: Schedule,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    bhp_limits: BhpLimits | None = None,
    zero_tolerance: float = DEFAULT_ZERO_TOLERANCE,
    watercut_tolerance: float = DEFAULT_WATERCUT_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    if oil_density_t_per_m3 <= 0.0:
        raise PhysicsCheckError("oil_density_t_per_m3 должна быть положительной")
    if zero_tolerance < 0.0:
        raise PhysicsCheckError("zero_tolerance не может быть отрицательным")
    if watercut_tolerance < 0.0:
        raise PhysicsCheckError("watercut_tolerance не может быть отрицательным")
    _require_same_axis(raw, schedule)

    limits = bhp_limits if bhp_limits is not None else BhpLimits.from_schedule(schedule)
    role_timelines = build_role_timelines(schedule)
    well_timelines = _build_well_timelines(schedule)
    sink = _FlagSink(max_examples)

    evaluated = list(_SINGLE_PREDICTION_INVARIANTS)
    skipped: dict[str, str] = {
        invariant.value: "инвариант определён только на паре опора/кандидат"
        for invariant in _DIFFERENTIAL_INVARIANTS
    }
    if not limits.usable:
        evaluated.remove(Invariant.BHP_LIMIT)
        skipped[Invariant.BHP_LIMIT.value] = (
            "дек не задаёт пределов BHP ни для одной скважины: "
            "WCONPROD/WCONINJE без числового значения предела"
        )

    for node in raw.nodes:
        role = role_timelines[node.well].role(node.control_step)
        _check_non_negative(node, sink=sink, tolerance=zero_tolerance)
        _check_watercut(
            node,
            sink=sink,
            oil_density_t_per_m3=oil_density_t_per_m3,
            zero_tolerance=zero_tolerance,
            watercut_tolerance=watercut_tolerance,
        )
        _check_cumulative(node, sink=sink, tolerance=zero_tolerance)
        _check_shut_well(
            node,
            sink=sink,
            timeline=well_timelines[node.well],
            tolerance=zero_tolerance,
        )
        if Invariant.BHP_LIMIT in evaluated:
            _check_bhp(node, sink=sink, role=role, limits=limits)

    return PhysicsReport(
        counts=sink.counts,
        examples=sink.examples,
        evaluated=tuple(evaluated),
        skipped=skipped,
        n_nodes=len(raw.nodes),
        n_wells=len(raw.wells),
    )


def injection_only_pair(
    reference_schedule: Schedule, candidate_schedule: Schedule
) -> tuple[bool, str]:
    def events(schedule: Schedule) -> dict[tuple[int, str, str], float | None]:
        return {
            (event.control_step, event.well, event.kind.value): getattr(event, "value", None)
            for event in schedule.control_events
        }

    left, right = events(reference_schedule), events(candidate_schedule)
    changed = {key for key in set(left) | set(right) if left.get(key) != right.get(key)}
    if not changed:
        return False, "опора и кандидат несут одинаковые управляющие события"
    other = sorted({key[2] for key in changed} - {EventKind.SET_RATE.value})
    if other:
        return False, f"кандидат меняет не только закачку: {', '.join(other)}"
    return True, ""


def lambda_column_sums(lam: Lambda) -> dict[str, float]:
    sums: dict[str, float] = {}
    for column, injector in enumerate(lam.injectors):
        sums[injector] = sum(lam.matrix[row][column] for row in range(len(lam.producers)))
    return sums


def _dominant_neighbourhoods(lam: Lambda) -> dict[str, tuple[str, ...]]:
    neighbourhoods: dict[str, list[str]] = {injector: [] for injector in lam.injectors}
    for row, producer in enumerate(lam.producers):
        weights = lam.matrix[row]
        best = max(range(len(lam.injectors)), key=lambda column: weights[column])
        if weights[best] > 0.0:
            neighbourhoods[lam.injectors[best]].append(producer)
    return {injector: tuple(producers) for injector, producers in neighbourhoods.items()}


def check_pair(
    reference: RawModelOutput,
    candidate: RawModelOutput,
    *,
    reference_schedule: Schedule,
    candidate_schedule: Schedule,
    lam: Lambda,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    if oil_density_t_per_m3 <= 0.0:
        raise PhysicsCheckError("oil_density_t_per_m3 должна быть положительной")
    if relative_tolerance < 0.0:
        raise PhysicsCheckError("relative_tolerance не может быть отрицательным")
    if reference.wells != candidate.wells:
        raise PhysicsCheckError("опора и кандидат построены на разных осях скважин")
    if reference.canonical_schedule_hash == candidate.canonical_schedule_hash:
        raise PhysicsCheckError(
            "опора и кандидат — одно расписание: differential-инварианты не определены"
        )

    known = set(reference.wells)
    missing = (set(lam.producers) | set(lam.injectors)) - known
    if missing:
        raise PhysicsCheckError(
            f"λ ссылается на скважины вне прогноза: {sorted(missing)[:5]}"
        )

    identifiable, reason = injection_only_pair(reference_schedule, candidate_schedule)
    if not identifiable:
        return PhysicsReport(
            counts={},
            examples=(),
            evaluated=(),
            skipped={invariant.value: reason for invariant in _DIFFERENTIAL_INVARIANTS},
            n_nodes=len(candidate.nodes),
            n_wells=len(candidate.wells),
        )

    delta_liquid = _horizon_delta(reference, candidate, "liquid_volume_delta")
    delta_oil_mass = _horizon_delta(reference, candidate, "oil_mass_delta")
    delta_injection = _horizon_delta(reference, candidate, "injection_volume_delta")
    sink = _FlagSink(max_examples)

    for injector, producers in _dominant_neighbourhoods(lam).items():
        injected = delta_injection.get(injector, 0.0)
        if not producers or injected <= _scaled_tolerance(injected, relative_tolerance):
            continue
        produced = sum(delta_liquid.get(producer, 0.0) for producer in producers)
        if produced < -_scaled_tolerance(injected, relative_tolerance):
            sink.add(
                Invariant.INJECTION_RESPONSE,
                well=injector,
                observed=produced,
                limit=0.0,
                detail=(
                    f"закачка выросла на {injected:.1f} м³, а суммарная жидкость "
                    f"{len(producers)} добывающих её окрестности упала на {-produced:.1f} м³"
                ),
            )

    injected_total = sum(delta_injection.get(well, 0.0) for well in lam.injectors)
    water_total = sum(
        delta_liquid.get(producer, 0.0)
        - delta_oil_mass.get(producer, 0.0) / oil_density_t_per_m3
        for producer in lam.producers
    )
    tolerance = _scaled_tolerance(max(water_total, injected_total), relative_tolerance)
    if water_total > injected_total + tolerance:
        sink.add(
            Invariant.MATERIAL_BALANCE,
            well="<поле>",
            observed=water_total,
            limit=injected_total,
            detail=(
                f"добыто воды на {water_total:.1f} м³ больше при приросте закачки "
                f"{injected_total:.1f} м³: вода взялась ниоткуда"
            ),
        )

    return PhysicsReport(
        counts=sink.counts,
        examples=sink.examples,
        evaluated=_DIFFERENTIAL_INVARIANTS,
        skipped={},
        n_nodes=len(candidate.nodes),
        n_wells=len(candidate.wells),
    )


def check_physics(
    candidate: RawModelOutput,
    *,
    schedule: Schedule,
    reference: RawModelOutput | None = None,
    reference_schedule: Schedule | None = None,
    lam: Lambda | None = None,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    bhp_limits: BhpLimits | None = None,
    zero_tolerance: float = DEFAULT_ZERO_TOLERANCE,
    watercut_tolerance: float = DEFAULT_WATERCUT_TOLERANCE,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    single = check_prediction(
        candidate,
        schedule=schedule,
        oil_density_t_per_m3=oil_density_t_per_m3,
        bhp_limits=bhp_limits,
        zero_tolerance=zero_tolerance,
        watercut_tolerance=watercut_tolerance,
        max_examples=max_examples,
    )
    if reference is None or reference_schedule is None or lam is None:
        absent = "опора" if reference is None or reference_schedule is None else "λ"
        return PhysicsReport(
            counts=single.counts,
            examples=single.examples,
            evaluated=single.evaluated,
            skipped={
                **single.skipped,
                **{
                    invariant.value: f"не передана {absent}: инвариант не определён"
                    for invariant in _DIFFERENTIAL_INVARIANTS
                },
            },
            n_nodes=single.n_nodes,
            n_wells=single.n_wells,
        )

    pair = check_pair(
        reference,
        candidate,
        reference_schedule=reference_schedule,
        candidate_schedule=schedule,
        lam=lam,
        oil_density_t_per_m3=oil_density_t_per_m3,
        relative_tolerance=relative_tolerance,
        max_examples=max_examples,
    )
    counts = dict(single.counts)
    for name, count in pair.counts.items():
        counts[name] = counts.get(name, 0) + count
    skipped = {
        name: reason
        for name, reason in single.skipped.items()
        if Invariant(name) not in _DIFFERENTIAL_INVARIANTS
    }
    skipped.update(pair.skipped)
    return PhysicsReport(
        counts=counts,
        examples=single.examples + pair.examples,
        evaluated=single.evaluated + pair.evaluated,
        skipped=skipped,
        n_nodes=single.n_nodes,
        n_wells=single.n_wells,
    )


def _require_same_axis(raw: RawModelOutput, schedule: Schedule) -> None:
    if set(raw.wells) != set(schedule.meta.wells):
        raise PhysicsCheckError(
            "ось скважин прогноза не совпадает с расписанием: "
            f"{len(raw.wells)} против {len(schedule.meta.wells)}"
        )


def _scaled_tolerance(magnitude: float, relative_tolerance: float) -> float:
    return abs(magnitude) * relative_tolerance


def _horizon_delta(
    reference: RawModelOutput, candidate: RawModelOutput, channel: str
) -> dict[str, float]:
    totals: dict[str, float] = {well: 0.0 for well in candidate.wells}
    for node in candidate.nodes:
        totals[node.well] += getattr(node, channel)
    for node in reference.nodes:
        totals[node.well] -= getattr(node, channel)
    return totals


def _check_non_negative(
    node: RawWellStepPrediction, *, sink: _FlagSink, tolerance: float
) -> None:
    for channel in _RATE_CHANNELS + _VOLUME_CHANNELS + ("bhp",):
        value = getattr(node, channel)
        if not math.isfinite(value):
            sink.add(
                Invariant.NON_NEGATIVE,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel} не конечно",
            )
        elif value < -tolerance:
            sink.add(
                Invariant.NON_NEGATIVE,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel} отрицательно",
            )


def _check_watercut(
    node: RawWellStepPrediction,
    *,
    sink: _FlagSink,
    oil_density_t_per_m3: float,
    zero_tolerance: float,
    watercut_tolerance: float,
) -> None:
    liquid = node.liquid_volume_delta
    oil_volume = node.oil_mass_delta / oil_density_t_per_m3
    if liquid <= zero_tolerance:
        if oil_volume > zero_tolerance:
            sink.add(
                Invariant.WATERCUT_RANGE,
                well=node.well,
                control_step=node.control_step,
                observed=oil_volume,
                limit=0.0,
                detail="нефть без жидкости: обводнённость не определена и меньше нуля",
            )
        return
    watercut = 1.0 - oil_volume / liquid
    if watercut < -watercut_tolerance:
        sink.add(
            Invariant.WATERCUT_RANGE,
            well=node.well,
            control_step=node.control_step,
            observed=watercut,
            limit=0.0,
            detail=(
                f"нефти {oil_volume:.3f} м³ при жидкости {liquid:.3f} м³: "
                f"обводнённость {watercut:.6f} меньше нуля"
            ),
        )
    elif watercut > 1.0 + watercut_tolerance:
        sink.add(
            Invariant.WATERCUT_RANGE,
            well=node.well,
            control_step=node.control_step,
            observed=watercut,
            limit=1.0,
            detail=f"обводнённость {watercut:.6f} больше единицы: добыча нефти отрицательна",
        )


def _check_cumulative(
    node: RawWellStepPrediction, *, sink: _FlagSink, tolerance: float
) -> None:
    for channel in _VOLUME_CHANNELS:
        value = getattr(node, channel)
        if math.isfinite(value) and value < -tolerance:
            sink.add(
                Invariant.CUMULATIVE_MONOTONIC,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel}: накопленная величина убывает на интервале",
            )


def _check_shut_well(
    node: RawWellStepPrediction, *, sink: _FlagSink, timeline: object, tolerance: float
) -> None:
    commissioned = timeline.is_commissioned(node.control_step)  # type: ignore[attr-defined]
    status = timeline.operating_status(node.control_step)  # type: ignore[attr-defined]
    if commissioned and status is OperatingStatus.OPEN:
        return
    reason = "не введена" if not commissioned else "закрыта"
    for channel in _RATE_CHANNELS + _VOLUME_CHANNELS:
        value = getattr(node, channel)
        if math.isfinite(value) and abs(value) > tolerance:
            sink.add(
                Invariant.SHUT_WELL_FLOW,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"скважина {reason}, а {channel} не ноль",
            )


def _check_bhp(
    node: RawWellStepPrediction, *, sink: _FlagSink, role: Role, limits: BhpLimits
) -> None:
    if role is Role.PROD:
        floor = limits.floor_for(node.well)
        if floor is not None and node.bhp < floor:
            sink.add(
                Invariant.BHP_LIMIT,
                well=node.well,
                control_step=node.control_step,
                observed=node.bhp,
                limit=floor,
                detail=f"забойное {node.bhp:.2f} бар ниже пола добывающей {floor:.2f} бар",
            )
    elif role is Role.INJ:
        ceiling = limits.ceiling_for(node.well)
        if ceiling is not None and node.bhp > ceiling:
            sink.add(
                Invariant.BHP_LIMIT,
                well=node.well,
                control_step=node.control_step,
                observed=node.bhp,
                limit=ceiling,
                detail=(
                    f"забойное {node.bhp:.2f} бар выше потолка нагнетательной "
                    f"{ceiling:.2f} бар"
                ),
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
    "PhysicsCheckError",
    "PhysicsFlag",
    "PhysicsReport",
    "Severity",
    "check_pair",
    "injection_only_pair",
    "lambda_column_sums",
    "check_physics",
    "check_prediction",
    "severity_of",
]
