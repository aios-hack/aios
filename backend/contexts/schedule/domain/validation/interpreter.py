from __future__ import annotations

from backend.contexts.schedule.domain.validation.constants import (
    FIRST_CONTROL_DECK_DATE_INDEX,
    FIRST_CONTROL_LEVEL_DECK_DATE_INDEX,
)

from collections.abc import (
    Iterable,
    Sequence,
)
from dataclasses import dataclass
from backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
    StateAtDate,
    WellState,
)


def level_deck_date_index(control_step: int) -> int:
    return FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + control_step


def control_step_of_level(deck_date_index: int) -> int:
    return deck_date_index - FIRST_CONTROL_LEVEL_DECK_DATE_INDEX


def control_step_pressures(
    field_pressure_bar: Sequence[float], n_intervals: int
) -> tuple[float, ...]:
    required = level_deck_date_index(n_intervals - 1) + 1
    if len(field_pressure_bar) < required:
        raise ValueError(
            f"серия FPR короче горизонта: {len(field_pressure_bar)} значений "
            f"при необходимых {required} = {FIRST_CONTROL_LEVEL_DECK_DATE_INDEX}"
            f" + {n_intervals}; уровень давления шага управления "
            f"{n_intervals - 1} читается по индексу дека "
            f"{level_deck_date_index(n_intervals - 1)}"
        )
    return tuple(
        field_pressure_bar[level_deck_date_index(step)]
        for step in range(n_intervals)
    )


@dataclass(frozen=True, slots=True)
class _Target:
    role: Role
    setpoint: float
    operating_status: OperatingStatus
    commissioned: bool
    setpoint_known: bool = True


def _target_timeline(
    schedule: Schedule,
) -> dict[str, tuple[tuple[int, _Target], ...]]:
    events_by_well: dict[str, list[ControlEvent]] = {}
    for event in schedule.control_events:
        events_by_well.setdefault(event.well, []).append(event)

    commissioning = _commissioning_steps(schedule)
    commissioned_roles = _commissioning_roles(schedule)
    timelines: dict[str, tuple[tuple[int, _Target], ...]] = {}
    wells = set(schedule.initial_state) | set(events_by_well)
    for well in wells:
        base = schedule.initial_state.get(well)
        current = _initial_target(base)
        points: list[tuple[int, _Target]] = [(-1, current)]
        introduced = commissioning.get(well)
        if introduced is not None and not current.commissioned:
            current = _Target(
                role=commissioned_roles.get(well, current.role),
                setpoint=current.setpoint,
                operating_status=OperatingStatus.OPEN,
                commissioned=True,
                setpoint_known=False,
            )
            points.append((introduced, current))
        for event in sorted(events_by_well.get(well, ()), key=lambda e: e.control_step):
            current = _apply_event(current, event)
            points.append((event.control_step, current))
        timelines[well] = tuple(points)
    return timelines


def _initial_target(state: WellState | None) -> _Target:
    if state is None:
        return _Target(Role.NONE, 0.0, OperatingStatus.SHUT, False, False)
    return _Target(
        role=state.role,
        setpoint=state.setpoint,
        operating_status=state.operating_status,
        commissioned=state.availability is Availability.AVAILABLE,
        setpoint_known=state.availability is Availability.AVAILABLE,
    )


def _commissioning_roles(schedule: Schedule) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for event in sorted(
        schedule.fixed_deck_events, key=lambda item: item.control_step
    ):
        if event.operator == "WCONPROD":
            roles.setdefault(event.well, Role.PROD)
        elif event.operator == "WCONINJE":
            roles.setdefault(event.well, Role.INJ)
    return roles


def _apply_event(current: _Target, event: ControlEvent) -> _Target:
    role = current.role
    setpoint = current.setpoint
    status = current.operating_status
    if event.kind is EventKind.CONVERT_INJ:
        role = Role.INJ
        setpoint = 0.0
    elif event.kind is EventKind.SET_LRAT:
        setpoint = event.value if event.value is not None else 0.0
        status = OperatingStatus.SHUT if setpoint == 0.0 else OperatingStatus.OPEN
    elif event.kind is EventKind.SET_RATE:
        setpoint = event.value if event.value is not None else 0.0
        status = OperatingStatus.SHUT if setpoint == 0.0 else OperatingStatus.OPEN
    elif event.kind is EventKind.OPEN:
        status = OperatingStatus.OPEN
    elif event.kind is EventKind.SHUT:
        status = OperatingStatus.SHUT
    known = current.setpoint_known or event.kind in (
        EventKind.SET_LRAT,
        EventKind.SET_RATE,
        EventKind.CONVERT_INJ,
    )
    return _Target(
        role=role,
        setpoint=setpoint,
        operating_status=status,
        commissioned=current.commissioned,
        setpoint_known=known,
    )


def _commissioning_steps(schedule: Schedule) -> dict[str, int]:
    steps: dict[str, int] = {}
    for event in schedule.fixed_deck_events:
        if event.operator not in ("WCONPROD", "WCONINJE"):
            continue
        current = steps.get(event.well)
        if current is None or event.control_step < current:
            steps[event.well] = event.control_step
    return steps


def _target_at(
    timeline: Sequence[tuple[int, _Target]], control_step: int
) -> _Target:
    result = timeline[0][1]
    for step, target in timeline:
        if step > control_step:
            break
        result = target
    return result


def _states_by_step(
    states: Iterable[StateAtDate],
) -> dict[tuple[int, str], StateAtDate]:
    indexed: dict[tuple[int, str], StateAtDate] = {}
    for state in states:
        control_step = state.deck_date_index - FIRST_CONTROL_DECK_DATE_INDEX - 1
        if control_step < 0:
            continue
        indexed[(control_step, state.well)] = state
    return indexed


def year_of_step(schedule: Schedule, control_step: int) -> int:
    t0 = schedule.meta.t0
    month_index = t0.month - 1 + control_step
    return t0.year + month_index // 12


__all__ = [
    "control_step_of_level",
    "control_step_pressures",
    "level_deck_date_index",
    "year_of_step",
]
