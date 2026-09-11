from __future__ import annotations

import hashlib
import random
from typing import Iterable, Sequence

from backend.contexts.simulation.domain.errors import DatasetPlanError
from backend.contexts.schedule.domain.schedule import MAX_LRAT_M3_PER_DAY, Schedule
from backend.contexts.simulation.domain.perturbation_spec import (
    BaselineProfile,
    ConversionToggle,
    LevelPerturbation,
    PerturbationFamily,
    PerturbationPlan,
    PerturbationSpec,
    PlanConfig,
    ShutdownWindow,
    UnreachableTarget,
    _well_sort_key,
    baseline_profile,
)

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
            "the base schedule has no CONVERT_INJ at all: there is nothing to build "
            "conversion-to-injection scenarios from"
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
            "the plan does not cover the mandatory kinds of §9.1: "
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

