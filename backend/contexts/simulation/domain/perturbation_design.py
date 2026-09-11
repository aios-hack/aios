from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.simulation.domain.errors import DatasetPlanError
from backend.contexts.schedule.domain.schedule import (
    Availability,
    ControlEvent,
    EventKind,
    MAX_LRAT_M3_PER_DAY,
    Role,
    Schedule,
    ScheduleMeta,
)
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
    dataset_base_schedule,
)
from backend.contexts.simulation.domain.perturbation_plan import (
    REQUIRED_FAMILIES,
    build_plan,
)

__all__ = [
    "REQUIRED_FAMILIES",
    "DatasetPlanError",
    "BaselineProfile",
    "ConversionToggle",
    "LevelPerturbation",
    "MaterializedSchedule",
    "PerturbationFamily",
    "PerturbationPlan",
    "PerturbationSpec",
    "PlanConfig",
    "ShutdownWindow",
    "UnreachableTarget",
    "baseline_profile",
    "build_plan",
    "commissioned_wells",
    "dataset_base_schedule",
    "materialize",
    "role_of",
]


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
