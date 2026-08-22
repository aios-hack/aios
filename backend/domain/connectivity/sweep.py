from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from backend.core.contracts import (
    ControlEvent,
    EventKind,
    IntervalResponse,
    Schedule,
    ScheduleMeta,
    StateAtDate,
)

from backend.domain.connectivity.amplitude import (
    AmplitudeMeasurement,
    AmplitudeProbe,
    ProbeOutcome,
    ProbeSelection,
)
from backend.domain.connectivity.doe import Amplitude, Level


class ResponseSource(Protocol):
    def state_at_date(self) -> Sequence[StateAtDate]: ...

    def interval_response(self) -> Sequence[IntervalResponse]: ...


@dataclass(frozen=True, slots=True)
class WindowSteps:
    first: int
    last: int

    def __post_init__(self) -> None:
        if self.first < 0:
            raise ValueError(f"первый шаг окна {self.first} отрицателен")
        if self.last < self.first:
            raise ValueError(
                f"окно замера пусто: last={self.last} < first={self.first}"
            )

    def contains(self, control_step: int) -> bool:
        return self.first <= control_step <= self.last

    @property
    def length(self) -> int:
        return self.last - self.first + 1


def injection_setpoints(
    schedule: Schedule, injectors: Sequence[str], control_step: int
) -> dict[str, float]:
    wanted = set(injectors)
    latest: dict[str, float] = {}
    earliest: dict[str, float] = {}
    for event in sorted(schedule.control_events, key=lambda e: e.control_step):
        if event.kind is not EventKind.SET_RATE or event.well not in wanted:
            continue
        value = event.value if event.value is not None else 0.0
        if event.control_step <= control_step:
            latest[event.well] = value
        elif event.well not in earliest:
            earliest[event.well] = value
    resolved = {well: latest.get(well, earliest.get(well)) for well in wanted}
    missing = sorted(well for well, value in resolved.items() if value is None)
    if missing:
        raise ValueError(
            f"в расписании нет ни одной уставки закачки для {missing}: "
            f"целевой уровень свипа назначается от факта, не от константы"
        )
    return {well: value for well, value in resolved.items() if value is not None}


def perturbed_schedule(
    baseline: Schedule,
    targets: Mapping[str, float],
    steps: WindowSteps,
    provenance: str,
) -> Schedule:
    if not targets:
        raise ValueError("возмущение без единой адресованной скважины")
    touched = set(targets)
    events: list[ControlEvent] = []
    for event in baseline.control_events:
        if (
            event.kind is EventKind.SET_RATE
            and event.well in touched
            and steps.contains(event.control_step)
        ):
            events.append(
                ControlEvent(
                    control_step=event.control_step,
                    well=event.well,
                    kind=EventKind.SET_RATE,
                    value=targets[event.well],
                )
            )
            continue
        events.append(event)
    replaced = {
        event.well
        for event in events
        if event.kind is EventKind.SET_RATE
        and event.well in touched
        and steps.contains(event.control_step)
        and event.value == targets[event.well]
    }
    unreached = touched - replaced
    if unreached:
        raise ValueError(
            f"в окне {steps.first}…{steps.last} нет ни одной уставки закачки для "
            f"{sorted(unreached)}: возмущение не материализовалось бы в деке"
        )
    meta = ScheduleMeta(
        model=baseline.meta.model,
        t0=baseline.meta.t0,
        n_control_dates=baseline.meta.n_control_dates,
        n_intervals=baseline.meta.n_intervals,
        wells=baseline.meta.wells,
        history_prefix_hash=baseline.meta.history_prefix_hash,
        fixed_events_hash=baseline.meta.fixed_events_hash,
        control_events_hash=baseline.meta.control_events_hash,
        provenance=provenance,
    )
    return Schedule(
        meta=meta,
        initial_state=baseline.initial_state,
        fixed_deck_events=baseline.fixed_deck_events,
        control_events=tuple(events),
    )


def mean_injection_rate(
    states: Sequence[StateAtDate],
    well: str,
    t0_deck_date_index: int,
    steps: WindowSteps,
) -> float:
    first = t0_deck_date_index + 1 + steps.first
    last = t0_deck_date_index + 1 + steps.last
    values = [
        state.injection_rate
        for state in states
        if state.well == well and first <= state.deck_date_index <= last
    ]
    if not values:
        raise ValueError(
            f"{well}: в окне дат {first}…{last} нет ни одной записи отклика"
        )
    return sum(values) / len(values)


def cumulative_liquid(
    intervals: Sequence[IntervalResponse],
    wells: Sequence[str],
    steps: WindowSteps,
) -> float:
    selected = set(wells)
    if not selected:
        raise ValueError("накопленная добыча по пустому списку скважин не определена")
    total = 0.0
    seen = False
    for interval in intervals:
        if interval.well not in selected:
            continue
        if not steps.contains(interval.control_step):
            continue
        total += interval.liquid_volume_delta
        seen = True
    if not seen:
        raise ValueError(
            f"в окне шагов {steps.first}…{steps.last} нет откликов по "
            f"{sorted(selected)}"
        )
    return total


def responders_of(
    probe_well: str, neighbours: Mapping[str, Sequence[str]]
) -> tuple[str, ...]:
    if probe_well not in neighbours:
        raise ValueError(f"{probe_well}: окружение не задано, отклик считать не по кому")
    listed = tuple(sorted(set(neighbours[probe_well])))
    if not listed:
        raise ValueError(f"{probe_well}: пустое окружение, замер отклика невозможен")
    return listed


@dataclass(frozen=True, slots=True)
class SweepRun:
    relative_amplitude: float
    well: str
    level: Level
    target_m3_per_day: float
    baseline_rate_m3_per_day: float
    actual_m3_per_day: float
    baseline_cumulative_m3: float
    perturbed_cumulative_m3: float


def build_probe(
    relative_amplitude: float,
    amplitude: Amplitude,
    runs: Sequence[SweepRun],
    noise_floor_m3: float,
) -> AmplitudeProbe:
    if not runs:
        raise ValueError(
            f"амплитуда {relative_amplitude}: ни одного прогона, замерять нечего"
        )
    outcomes = tuple(
        ProbeOutcome(
            well=run.well,
            level=run.level,
            amplitude=amplitude,
            target_m3_per_day=run.target_m3_per_day,
            actual_m3_per_day=run.actual_m3_per_day,
            baseline_cumulative_m3=run.baseline_cumulative_m3,
            perturbed_cumulative_m3=run.perturbed_cumulative_m3,
        )
        for run in runs
    )
    return AmplitudeProbe(
        relative_amplitude=relative_amplitude,
        amplitude=amplitude,
        outcomes=outcomes,
        noise_floor_m3=noise_floor_m3,
    )


def build_measurement(
    probes: Sequence[AmplitudeProbe],
    achievability_tolerance: float,
    linearity_tolerance: float,
) -> AmplitudeMeasurement:
    return AmplitudeMeasurement(
        probes=tuple(probes),
        achievability_tolerance=achievability_tolerance,
        linearity_tolerance=linearity_tolerance,
    )


def sweep_targets(
    selection: ProbeSelection,
    amplitude: Amplitude,
    current_by_well: Mapping[str, float],
    level: Level,
) -> dict[str, float]:
    missing = set(selection.wells) - set(current_by_well)
    if missing:
        raise ValueError(f"нет текущего уровня закачки для {sorted(missing)}")
    return {
        well: amplitude.target(level, current_by_well[well])
        for well in selection.wells
    }
