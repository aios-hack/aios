from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping

from backend.contexts.simulation.domain.errors import DatasetPlanError
from backend.contexts.schedule.domain.schedule import (
    EventKind,
    Schedule,
    ScheduleMeta,
)
from backend.shared.hashing import canonical_bytes
from backend.contexts.schedule.domain.build import load_schedule
from backend.contexts.simulation.domain.ports import WellStockSource

_SCHEDULE_INCLUDE = "Model_Z_sch.inc"


class PerturbationFamily(Enum):
    BASELINE = "BASELINE"
    LEVELS = "LEVELS"
    UNREACHABLE = "UNREACHABLE"
    SHUTDOWN = "SHUTDOWN"
    CONVERSION = "CONVERSION"


@dataclass(frozen=True, slots=True)
class LevelPerturbation:
    well: str
    from_step: int
    factor: float


@dataclass(frozen=True, slots=True)
class UnreachableTarget:
    well: str
    from_step: int
    setpoint: float


@dataclass(frozen=True, slots=True)
class ShutdownWindow:
    well: str
    from_step: int
    to_step: int


@dataclass(frozen=True, slots=True)
class ConversionToggle:
    well: str
    control_step: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class PerturbationSpec:
    scenario_id: str
    family: PerturbationFamily
    seed: int
    levels: tuple[LevelPerturbation, ...] = ()
    unreachable: tuple[UnreachableTarget, ...] = ()
    shutdowns: tuple[ShutdownWindow, ...] = ()
    conversions: tuple[ConversionToggle, ...] = ()

    @property
    def spec_hash(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @property
    def n_unreachable_targets(self) -> int:
        return len(self.unreachable)


@dataclass(frozen=True, slots=True)
class PlanConfig:
    n_level_scenarios: int = 24
    n_unreachable_scenarios: int = 8
    n_shutdown_scenarios: int = 8
    n_conversion_scenarios: int = 4
    include_baseline: bool = True
    allow_conversion_retiming: bool = False

    level_factor_low: float = 0.5
    level_factor_high: float = 1.5
    level_wells_fraction: float = 0.4

    unreachable_wells_fraction: float = 0.15
    unreachable_overshoot: float = 4.0

    shutdown_wells_fraction: float = 0.1
    shutdown_min_length: int = 3
    shutdown_max_length: int = 24

    conversion_drop_probability: float = 0.5

    def __post_init__(self) -> None:
        if self.allow_conversion_retiming:
            raise DatasetPlanError(
                "allow_conversion_retiming=true is forbidden until the organizers answer "
                "on §3.11: moving the conversion date yields a physically ambiguous deck "
                "(contract §9.1, decision of 14.08)"
            )
        if not (0.0 < self.level_factor_low <= self.level_factor_high):
            raise DatasetPlanError("the level multiplier window is set incorrectly")
        if self.unreachable_overshoot <= 1.0:
            raise DatasetPlanError("an unreachable setpoint must exceed the base one")
        if self.shutdown_min_length < 1 or self.shutdown_max_length < self.shutdown_min_length:
            raise DatasetPlanError("the shut-in duration window is set incorrectly")


@dataclass(frozen=True, slots=True)
class BaselineProfile:
    wells: tuple[str, ...]
    n_intervals: int
    producers: tuple[str, ...]
    injectors: tuple[str, ...]
    max_setpoint: Mapping[str, float]
    first_controlled_step: Mapping[str, int]
    conversion_steps: Mapping[str, int]

    @property
    def controllable(self) -> tuple[str, ...]:
        return tuple(sorted(self.first_controlled_step, key=_well_sort_key))


def _well_sort_key(well: str) -> str:
    return well


def baseline_profile(schedule: Schedule) -> BaselineProfile:
    meta: ScheduleMeta = schedule.meta
    conversion_steps: dict[str, int] = {}
    for event in schedule.control_events:
        if event.kind is EventKind.CONVERT_INJ:
            if event.well in conversion_steps:
                raise DatasetPlanError(
                    f"well {event.well!r}: two CONVERT_INJ in the base, the plan is ambiguous"
                )
            conversion_steps[event.well] = event.control_step

    max_setpoint: dict[str, float] = {}
    first_step: dict[str, int] = {}
    kinds: dict[str, set[EventKind]] = {}
    for event in schedule.control_events:
        if event.kind not in (EventKind.SET_LRAT, EventKind.SET_RATE):
            continue
        well = event.well
        value = 0.0 if event.value is None else event.value
        current = max_setpoint.get(well)
        if current is None or value > current:
            max_setpoint[well] = value
        step = first_step.get(well)
        if step is None or event.control_step < step:
            first_step[well] = event.control_step
        kinds.setdefault(well, set()).add(event.kind)

    producers: list[str] = []
    injectors: list[str] = []
    for well in sorted(kinds, key=_well_sort_key):
        well_kinds = kinds[well]
        if well in conversion_steps:
            injectors.append(well)
        elif well_kinds == {EventKind.SET_LRAT}:
            producers.append(well)
        elif well_kinds == {EventKind.SET_RATE}:
            injectors.append(well)
        else:
            raise DatasetPlanError(
                f"well {well!r}: mixed setpoints without CONVERT_INJ, the role is undetermined"
            )

    return BaselineProfile(
        wells=tuple(meta.wells),
        n_intervals=meta.n_intervals,
        producers=tuple(producers),
        injectors=tuple(injectors),
        max_setpoint=dict(max_setpoint),
        first_controlled_step=dict(first_step),
        conversion_steps=dict(conversion_steps),
    )


def dataset_base_schedule(model_dir: Path | str, emitter: WellStockSource) -> Schedule:
    model_dir = Path(model_dir)
    loaded = load_schedule(model_dir / _SCHEDULE_INCLUDE, provenance="Model_Z baseline")
    if set(loaded.meta.wells) != set(emitter.source_wells):
        raise DatasetPlanError(
            "the well axis of the parsed schedule does not match the deck WELSPECS"
        )
    meta = ScheduleMeta(
        model=loaded.meta.model,
        t0=loaded.meta.t0,
        n_control_dates=loaded.meta.n_control_dates,
        n_intervals=loaded.meta.n_intervals,
        wells=emitter.source_wells,
        history_prefix_hash=loaded.meta.history_prefix_hash,
        fixed_events_hash=loaded.meta.fixed_events_hash,
        control_events_hash=loaded.meta.control_events_hash,
        provenance=loaded.meta.provenance,
    )
    return Schedule(
        meta=meta,
        initial_state=loaded.initial_state,
        fixed_deck_events=loaded.fixed_deck_events,
        control_events=loaded.control_events,
    )


@dataclass(frozen=True, slots=True)
class PerturbationPlan:
    config: PlanConfig
    seed: int
    specs: tuple[PerturbationSpec, ...] = field(default_factory=tuple)

    @property
    def plan_hash(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    def families(self) -> frozenset[PerturbationFamily]:
        return frozenset(spec.family for spec in self.specs)

    def by_family(self, family: PerturbationFamily) -> tuple[PerturbationSpec, ...]:
        return tuple(spec for spec in self.specs if spec.family is family)

    def __len__(self) -> int:
        return len(self.specs)

    def __iter__(self):
        return iter(self.specs)

