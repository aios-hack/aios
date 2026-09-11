from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from backend.contexts.simulation.domain.errors import ResponseLoaderError
from backend.contexts.schedule.domain.wcon import CONTROL_ORDER, commissioning_state
from backend.contexts.schedule.domain.schedule import (
    Availability,
    EventKind,
    OperatingStatus,
    Schedule,
)


@dataclass(frozen=True, slots=True)
class _WellTimeline:
    baseline_available: bool
    baseline_operating_status: OperatingStatus
    baseline_setpoint: float
    status_steps: tuple[int, ...]
    status_values: tuple[OperatingStatus, ...]
    setpoint_steps: tuple[int, ...]
    setpoint_values: tuple[float, ...]
    first_commission_step: int | None

    def is_commissioned(self, control_step: int) -> bool:
        if self.baseline_available:
            return True
        return self.first_commission_step is not None and self.first_commission_step <= control_step

    def operating_status(self, control_step: int) -> OperatingStatus:
        index = bisect_right(self.status_steps, control_step) - 1
        if index >= 0:
            return self.status_values[index]
        return self.baseline_operating_status

    def setpoint(self, control_step: int) -> float:
        index = bisect_right(self.setpoint_steps, control_step) - 1
        if index >= 0:
            return self.setpoint_values[index]
        return self.baseline_setpoint


def build_well_timelines(schedule: Schedule) -> dict[str, _WellTimeline]:
    events_by_well: dict[str, list[tuple[int, int, object]]] = {}
    for event in schedule.fixed_deck_events:
        if event.operator in {"WCONPROD", "WCONINJE"}:
            events_by_well.setdefault(event.well, []).append((event.control_step, -1, event))
    for event in schedule.control_events:
        events_by_well.setdefault(event.well, []).append(
            (event.control_step, CONTROL_ORDER[event.kind], event)
        )
    wells = set(schedule.initial_state) | set(events_by_well)
    timelines: dict[str, _WellTimeline] = {}
    for well in wells:
        baseline = schedule.initial_state.get(well)
        status_steps, status_values, setpoint_steps, setpoint_values = [], [], [], []
        first_commission: int | None = None
        for step, priority, event in sorted(events_by_well.get(well, ()), key=lambda row: row[:2]):
            if priority == -1:
                try:
                    fixed = commissioning_state(event.operator, event.raw_args)
                except ValueError as error:
                    raise ResponseLoaderError(f"{well}, step {step}: {error}") from error
                status_steps.append(step)
                status_values.append(fixed.operating_status)
                setpoint_steps.append(step)
                setpoint_values.append(fixed.setpoint)
                if first_commission is None:
                    first_commission = step
            elif event.kind in (EventKind.OPEN, EventKind.SHUT):
                status_steps.append(step)
                status_values.append(
                    OperatingStatus.OPEN if event.kind is EventKind.OPEN else OperatingStatus.SHUT
                )
                if event.kind is EventKind.OPEN and first_commission is None:
                    first_commission = step
            elif event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
                setpoint_steps.append(step)
                setpoint_values.append(event.value if event.value is not None else 0.0)
        timelines[well] = _WellTimeline(
            baseline_available=(baseline is not None and baseline.availability is Availability.AVAILABLE),
            baseline_operating_status=(
                baseline.operating_status if baseline is not None else OperatingStatus.SHUT
            ),
            baseline_setpoint=baseline.setpoint if baseline is not None else 0.0,
            status_steps=tuple(status_steps), status_values=tuple(status_values),
            setpoint_steps=tuple(setpoint_steps), setpoint_values=tuple(setpoint_values),
            first_commission_step=first_commission,
        )
    return timelines
