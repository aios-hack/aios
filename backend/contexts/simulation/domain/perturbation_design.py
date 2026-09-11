
from __future__ import annotations

from backend.contexts.simulation.domain.errors import (
    DatasetPlanError,
)

import hashlib
import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    MAX_LRAT_M3_PER_DAY,
    Role,
    Schedule,
    ScheduleMeta,
    canonical_bytes,
)
from backend.domain.schedule import load_schedule

from backend.contexts.reservoir.infrastructure.opm_deck import OpmDeckEmitter

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
                "allow_conversion_retiming=true запрещён до ответа организаторов "
                "по §3.11: перенос даты перевода даёт физически неоднозначный дек "
                "(контракт §9.1, решение 14.08)"
            )
        if not (0.0 < self.level_factor_low <= self.level_factor_high):
            raise DatasetPlanError("окно множителей уровней задано неверно")
        if self.unreachable_overshoot <= 1.0:
            raise DatasetPlanError("недостижимая уставка обязана превышать базовую")
        if self.shutdown_min_length < 1 or self.shutdown_max_length < self.shutdown_min_length:
            raise DatasetPlanError("окно длительности остановки задано неверно")


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
                    f"скважина {event.well!r}: в базе два CONVERT_INJ, план не однозначен"
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
                f"скважина {well!r}: смешанные уставки без CONVERT_INJ, роль не определена"
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


def dataset_base_schedule(
    model_dir: Path | str, emitter: OpmDeckEmitter | None = None
) -> Schedule:
    model_dir = Path(model_dir)
    emitter = emitter or OpmDeckEmitter(model_dir)
    loaded = load_schedule(model_dir / _SCHEDULE_INCLUDE, provenance="Model_Z baseline")
    if set(loaded.meta.wells) != set(emitter.source_wells):
        raise DatasetPlanError(
            "ось скважин разобранного расписания не совпадает с WELSPECS дека"
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


def _sample_wells(rng: random.Random, wells: Sequence[str], fraction: float) -> tuple[str, ...]:
    if not wells:
        return ()
    count = max(1, round(len(wells) * fraction))
    count = min(count, len(wells))
    return tuple(sorted(rng.sample(list(wells), count), key=_well_sort_key))


def _latin_hypercube(rng: random.Random, n_points: int, low: float, high: float) -> list[float]:
    if n_points <= 0:
        return []
    width = (high - low) / n_points
    values = [low + width * (index + rng.random()) for index in range(n_points)]
    rng.shuffle(values)
    return values


def _earliest_step(profile: BaselineProfile, well: str) -> int:
    return profile.first_controlled_step.get(well, 0)


def _perturbation_start(rng: random.Random, profile: BaselineProfile, well: str) -> int:
    earliest = _earliest_step(profile, well)
    latest = max(earliest, profile.n_intervals - 1)
    return rng.randint(earliest, latest)


def _levels_spec(
    scenario_id: str, seed: int, profile: BaselineProfile, config: PlanConfig
) -> PerturbationSpec:
    rng = random.Random(seed)
    wells = _sample_wells(rng, profile.controllable, config.level_wells_fraction)
    factors = _latin_hypercube(
        rng, len(wells), config.level_factor_low, config.level_factor_high
    )
    levels = tuple(
        LevelPerturbation(
            well=well,
            from_step=_perturbation_start(rng, profile, well),
            factor=factor,
        )
        for well, factor in zip(wells, factors)
    )
    return PerturbationSpec(
        scenario_id=scenario_id,
        family=PerturbationFamily.LEVELS,
        seed=seed,
        levels=levels,
    )


def _unreachable_spec(
    scenario_id: str, seed: int, profile: BaselineProfile, config: PlanConfig
) -> PerturbationSpec:
    rng = random.Random(seed)
    wells = _sample_wells(rng, profile.controllable, config.unreachable_wells_fraction)
    targets: list[UnreachableTarget] = []
    for well in wells:
        base = profile.max_setpoint.get(well, 0.0)
        if base <= 0.0:
            continue
        setpoint = base * config.unreachable_overshoot
        if well in profile.producers:
            setpoint = min(setpoint, MAX_LRAT_M3_PER_DAY)
            if setpoint <= base:
                continue
        targets.append(
            UnreachableTarget(
                well=well,
                from_step=_perturbation_start(rng, profile, well),
                setpoint=setpoint,
            )
        )
    return PerturbationSpec(
        scenario_id=scenario_id,
        family=PerturbationFamily.UNREACHABLE,
        seed=seed,
        unreachable=tuple(targets),
    )


def _shutdown_spec(
    scenario_id: str, seed: int, profile: BaselineProfile, config: PlanConfig
) -> PerturbationSpec:
    rng = random.Random(seed)
    wells = _sample_wells(rng, profile.controllable, config.shutdown_wells_fraction)
    windows: list[ShutdownWindow] = []
    for well in wells:
        earliest = _earliest_step(profile, well)
        latest = profile.n_intervals - 1
        if earliest >= latest:
            continue
        from_step = rng.randint(earliest, latest - 1)
        length = rng.randint(config.shutdown_min_length, config.shutdown_max_length)
        to_step = min(from_step + length, profile.n_intervals)
        windows.append(ShutdownWindow(well=well, from_step=from_step, to_step=to_step))
    return PerturbationSpec(
        scenario_id=scenario_id,
        family=PerturbationFamily.SHUTDOWN,
        seed=seed,
        shutdowns=tuple(windows),
    )


def _conversion_spec(
    scenario_id: str, seed: int, profile: BaselineProfile, config: PlanConfig
) -> PerturbationSpec:
    rng = random.Random(seed)
    toggles = tuple(
        ConversionToggle(
            well=well,
            control_step=profile.conversion_steps[well],
            enabled=rng.random() >= config.conversion_drop_probability,
        )
        for well in sorted(profile.conversion_steps, key=_well_sort_key)
    )
    return PerturbationSpec(
        scenario_id=scenario_id,
        family=PerturbationFamily.CONVERSION,
        seed=seed,
        conversions=toggles,
    )


_BUILDERS = {
    PerturbationFamily.LEVELS: _levels_spec,
    PerturbationFamily.UNREACHABLE: _unreachable_spec,
    PerturbationFamily.SHUTDOWN: _shutdown_spec,
    PerturbationFamily.CONVERSION: _conversion_spec,
}


def _scenario_seed(plan_seed: int, family: PerturbationFamily, index: int) -> int:
    payload = f"{plan_seed}:{family.value}:{index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def build_plan(
    schedule: Schedule,
    *,
    seed: int,
    config: PlanConfig | None = None,
) -> PerturbationPlan:
    config = config or PlanConfig()
    profile = baseline_profile(schedule)
    if not profile.conversion_steps:
        raise DatasetPlanError(
            "в базовом расписании нет ни одного CONVERT_INJ: сценарии перевода "
            "под закачку строить не из чего"
        )

    counts = (
        (PerturbationFamily.LEVELS, config.n_level_scenarios),
        (PerturbationFamily.UNREACHABLE, config.n_unreachable_scenarios),
        (PerturbationFamily.SHUTDOWN, config.n_shutdown_scenarios),
        (PerturbationFamily.CONVERSION, config.n_conversion_scenarios),
    )
    specs: list[PerturbationSpec] = []
    if config.include_baseline:
        specs.append(
            PerturbationSpec(
                scenario_id="baseline",
                family=PerturbationFamily.BASELINE,
                seed=seed,
            )
        )
    for family, count in counts:
        for index in range(count):
            scenario_seed = _scenario_seed(seed, family, index)
            scenario_id = f"{family.value.lower()}-{index:04d}"
            specs.append(
                _BUILDERS[family](scenario_id, scenario_seed, profile, config)
            )

    missing = _missing_families(specs, config)
    if missing:
        raise DatasetPlanError(
            "план не покрывает обязательные виды §9.1: "
            + ", ".join(sorted(item.value for item in missing))
        )
    return PerturbationPlan(config=config, seed=seed, specs=tuple(specs))


REQUIRED_FAMILIES: frozenset[PerturbationFamily] = frozenset(
    {
        PerturbationFamily.LEVELS,
        PerturbationFamily.UNREACHABLE,
        PerturbationFamily.SHUTDOWN,
        PerturbationFamily.CONVERSION,
    }
)


def _missing_families(
    specs: Iterable[PerturbationSpec], config: PlanConfig
) -> frozenset[PerturbationFamily]:
    covered: set[PerturbationFamily] = set()
    for spec in specs:
        if spec.family is PerturbationFamily.LEVELS and spec.levels:
            covered.add(spec.family)
        elif spec.family is PerturbationFamily.UNREACHABLE and spec.unreachable:
            covered.add(spec.family)
        elif spec.family is PerturbationFamily.SHUTDOWN and spec.shutdowns:
            covered.add(spec.family)
        elif spec.family is PerturbationFamily.CONVERSION and any(
            not toggle.enabled for toggle in spec.conversions
        ):
            covered.add(spec.family)
    return REQUIRED_FAMILIES - covered


@dataclass(frozen=True, slots=True)
class MaterializedSchedule:
    spec: PerturbationSpec
    schedule: Schedule
    unreachable_fraction: float


def _dense_index(
    schedule: Schedule,
) -> dict[tuple[int, str], list[ControlEvent]]:
    dense: dict[tuple[int, str], list[ControlEvent]] = {}
    for event in schedule.control_events:
        dense.setdefault((event.control_step, event.well), []).append(event)
    return dense


def materialize(
    base: Schedule, spec: PerturbationSpec, *, provenance: str | None = None
) -> MaterializedSchedule:
    profile = baseline_profile(base)
    levels = {item.well: item for item in spec.levels}
    unreachable = {item.well: item for item in spec.unreachable}
    shutdowns: dict[str, list[ShutdownWindow]] = {}
    for window in spec.shutdowns:
        shutdowns.setdefault(window.well, []).append(window)
    dropped_conversions = {
        toggle.well for toggle in spec.conversions if not toggle.enabled
    }

    dense = _dense_index(base)
    events: list[ControlEvent] = []
    last_producer_setpoint: dict[str, float] = {}
    n_unreachable = 0
    n_targets = 0

    for (step, well), well_events in sorted(
        dense.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        drops_conversion = well in dropped_conversions
        conversion_step = profile.conversion_steps.get(well)
        after_dropped_conversion = (
            drops_conversion
            and conversion_step is not None
            and step >= conversion_step
        )

        convert = any(event.kind is EventKind.CONVERT_INJ for event in well_events)
        target: ControlEvent | None = None
        status_kind = EventKind.OPEN
        for event in well_events:
            if event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
                if convert and event.kind is not EventKind.SET_RATE:
                    continue
                if after_dropped_conversion and event.kind is EventKind.SET_RATE:
                    continue
                target = event
            elif event.kind in (EventKind.OPEN, EventKind.SHUT):
                if convert:
                    continue
                status_kind = event.kind

        if after_dropped_conversion:
            convert = False
            status_kind = EventKind.OPEN

        if target is None:
            if not after_dropped_conversion:
                continue
            kind = EventKind.SET_LRAT
            value = last_producer_setpoint.get(well, 0.0)
        else:
            kind = target.kind
            value = 0.0 if target.value is None else target.value
            if after_dropped_conversion:
                kind = EventKind.SET_LRAT
                if value == 0.0:
                    value = last_producer_setpoint.get(well, 0.0)

        n_targets += 1
        unreachable_target = unreachable.get(well)
        if unreachable_target is not None and step >= unreachable_target.from_step:
            value = unreachable_target.setpoint
            n_unreachable += 1
        else:
            level = levels.get(well)
            if level is not None and step >= level.from_step:
                value = value * level.factor

        if kind is EventKind.SET_LRAT:
            value = min(value, MAX_LRAT_M3_PER_DAY)
        value = max(value, 0.0)
        if kind is EventKind.SET_LRAT and not convert and value > 0.0:
            last_producer_setpoint[well] = value

        shut_here = any(
            window.from_step <= step < window.to_step
            for window in shutdowns.get(well, ())
        )
        if shut_here and not convert:
            status_kind = EventKind.SHUT
            value = 0.0

        if convert:
            events.append(ControlEvent(control_step=step, well=well, kind=EventKind.CONVERT_INJ))
            events.append(ControlEvent(control_step=step, well=well, kind=EventKind.SET_LRAT, value=0.0))
            events.append(ControlEvent(control_step=step, well=well, kind=EventKind.SET_RATE, value=value))
            events.append(ControlEvent(control_step=step, well=well, kind=EventKind.OPEN))
            events.append(ControlEvent(control_step=step, well=well, kind=EventKind.SHUT))
            continue

        events.append(ControlEvent(control_step=step, well=well, kind=kind, value=value))
        events.append(ControlEvent(control_step=step, well=well, kind=status_kind))

    meta = ScheduleMeta(
        model=base.meta.model,
        t0=base.meta.t0,
        n_control_dates=base.meta.n_control_dates,
        n_intervals=base.meta.n_intervals,
        wells=base.meta.wells,
        history_prefix_hash=base.meta.history_prefix_hash,
        fixed_events_hash=base.meta.fixed_events_hash,
        control_events_hash=base.meta.control_events_hash,
        provenance=provenance or f"dataset:{spec.scenario_id}:{spec.spec_hash[:12]}",
    )
    schedule = Schedule(
        meta=meta,
        initial_state=base.initial_state,
        fixed_deck_events=base.fixed_deck_events,
        control_events=tuple(events),
    )
    fraction = 0.0 if n_targets == 0 else n_unreachable / n_targets
    return MaterializedSchedule(spec=spec, schedule=schedule, unreachable_fraction=fraction)


def commissioned_wells(schedule: Schedule) -> tuple[str, ...]:
    return tuple(
        sorted(
            (
                well
                for well, state in schedule.initial_state.items()
                if state.availability is Availability.AVAILABLE
            ),
            key=_well_sort_key,
        )
    )


def role_of(schedule: Schedule, well: str) -> Role:
    state = schedule.initial_state.get(well)
    return Role.NONE if state is None else state.role
