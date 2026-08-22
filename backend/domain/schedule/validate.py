from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from backend.core.contracts import (
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    MAX_LRAT_M3_PER_DAY,
    N_INTERVALS,
    Role,
    Schedule,
    WellState,
)

from .canonical import canonical_part_hash, find_control_conflicts

MIN_SETPOINT_M3_PER_DAY: float = 0.0

_COMMISSIONING_OPERATORS: frozenset[str] = frozenset({"WCONPROD", "WCONINJE"})


class ViolationKind(Enum):
    LRAT_ABOVE_CEILING = "LRAT_ABOVE_CEILING"
    NEGATIVE_SETPOINT = "NEGATIVE_SETPOINT"
    MISSING_VALUE = "MISSING_VALUE"
    UNEXPECTED_VALUE = "UNEXPECTED_VALUE"
    STEP_OUT_OF_RANGE = "STEP_OUT_OF_RANGE"
    TERMINAL_STEP_HAS_CONTROL = "TERMINAL_STEP_HAS_CONTROL"
    WELL_NOT_ON_AXIS = "WELL_NOT_ON_AXIS"
    WELL_NOT_COMMISSIONED = "WELL_NOT_COMMISSIONED"
    SET_LRAT_ON_INJECTOR = "SET_LRAT_ON_INJECTOR"
    SET_RATE_ON_PRODUCER = "SET_RATE_ON_PRODUCER"
    CONVERT_INJ_REPEATED = "CONVERT_INJ_REPEATED"
    CONVERT_INJ_ON_INJECTOR = "CONVERT_INJ_ON_INJECTOR"
    CONFLICTING_EVENTS = "CONFLICTING_EVENTS"
    FIXED_LAYER_CHANGED = "FIXED_LAYER_CHANGED"
    WELL_OUTAGE_VIOLATED = "WELL_OUTAGE_VIOLATED"
    TARGET_UNDERSHOOT = "TARGET_UNDERSHOOT"
    BHP_BELOW_PRODUCER_LIMIT = "BHP_BELOW_PRODUCER_LIMIT"
    BHP_ABOVE_INJECTOR_LIMIT = "BHP_ABOVE_INJECTOR_LIMIT"
    MODE_NOT_REPORTED = "MODE_NOT_REPORTED"
    MODE_CONTRADICTS_SCHEDULE = "MODE_CONTRADICTS_SCHEDULE"
    BHP_LIMITED_WITHOUT_UNDERSHOOT = "BHP_LIMITED_WITHOUT_UNDERSHOOT"
    ROLE_FACT_MISMATCH = "ROLE_FACT_MISMATCH"
    OPEN_WITHOUT_FLOW = "OPEN_WITHOUT_FLOW"
    SHUT_WITH_FLOW = "SHUT_WITH_FLOW"
    NEGATIVE_INTERVAL_DELTA = "NEGATIVE_INTERVAL_DELTA"
    RESPONSE_AXIS_INCOMPLETE = "RESPONSE_AXIS_INCOMPLETE"
    LIQUID_LIMIT_EXCEEDED = "LIQUID_LIMIT_EXCEEDED"
    INJECTION_LIMIT_EXCEEDED = "INJECTION_LIMIT_EXCEEDED"
    PRODUCTION_FLOOR_MISSED = "PRODUCTION_FLOOR_MISSED"
    WATERCUT_LIMIT_EXCEEDED = "WATERCUT_LIMIT_EXCEEDED"
    OUTAGE_WELL_PRODUCED = "OUTAGE_WELL_PRODUCED"


@dataclass(frozen=True, slots=True)
class Violation:
    kind: ViolationKind
    control_step: int | None
    well: str | None
    value: float | None
    detail: str

    def __str__(self) -> str:
        where = []
        if self.control_step is not None:
            where.append(f"control_step={self.control_step}")
        if self.well is not None:
            where.append(f"скважина {self.well!r}")
        location = ", ".join(where) if where else "расписание"
        value = "" if self.value is None else f", значение {self.value!r}"
        return f"[{self.kind.value}] {location}{value}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ValidationReport:
    violations: tuple[Violation, ...]
    n_control_events: int
    n_fixed_events: int
    n_intervals: int

    @property
    def ok(self) -> bool:
        return not self.violations

    def by_kind(self) -> dict[ViolationKind, tuple[Violation, ...]]:
        buckets: dict[ViolationKind, list[Violation]] = {}
        for violation in self.violations:
            buckets.setdefault(violation.kind, []).append(violation)
        return {kind: tuple(items) for kind, items in buckets.items()}

    def counts(self) -> dict[ViolationKind, int]:
        return {kind: len(items) for kind, items in self.by_kind().items()}

    def format(self, limit: int = 50) -> str:
        if self.ok:
            return (
                f"нарушений нет: {self.n_control_events} управляющих событий, "
                f"{self.n_fixed_events} фиксированных, {self.n_intervals} интервалов"
            )
        head = "\n".join(str(item) for item in self.violations[:limit])
        tail = (
            f"\n… ещё {len(self.violations) - limit}"
            if len(self.violations) > limit
            else ""
        )
        return f"нарушений {len(self.violations)}:\n{head}{tail}"

    def raise_if_violated(self) -> None:
        if not self.ok:
            raise StaticValidationError(self.format(), self)


class StaticValidationError(ValueError):
    def __init__(self, message: str, report: ValidationReport) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    control_step: int
    well: str
    kind: EventKind
    value: float | None = None


def _well_sort_key(well: str) -> tuple[int, int, str]:
    return (0, int(well), well) if well.isdigit() else (1, 0, well)


def _event_sort_key(event: CandidateEvent) -> tuple[int, tuple[int, int, str], str]:
    return (event.control_step, _well_sort_key(event.well), event.kind.name)


def as_candidate(event: ControlEvent | CandidateEvent) -> CandidateEvent:
    if isinstance(event, CandidateEvent):
        return event
    return CandidateEvent(
        control_step=event.control_step,
        well=event.well,
        kind=event.kind,
        value=event.value,
    )


def candidates(
    events: Iterable[ControlEvent | CandidateEvent],
) -> tuple[CandidateEvent, ...]:
    return tuple(as_candidate(event) for event in events)


def check_lrat_ceiling(
    events: Sequence[CandidateEvent],
    ceiling: float = MAX_LRAT_M3_PER_DAY,
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for event in sorted(events, key=_event_sort_key):
        if event.kind is not EventKind.SET_LRAT or event.value is None:
            continue
        if event.value > ceiling:
            found.append(
                Violation(
                    kind=ViolationKind.LRAT_ABOVE_CEILING,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=(
                        f"уставка LRAT превышает потолок Методики {ceiling} м³/сут "
                        f"на {event.value - ceiling} м³/сут; эталонный расчётчик "
                        f"на таком входе падает с ошибкой"
                    ),
                )
            )
    return tuple(found)


def check_setpoint_ranges(
    events: Sequence[CandidateEvent],
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for event in sorted(events, key=_event_sort_key):
        needs_value = event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE)
        if needs_value and event.value is None:
            found.append(
                Violation(
                    kind=ViolationKind.MISSING_VALUE,
                    control_step=event.control_step,
                    well=event.well,
                    value=None,
                    detail=f"{event.kind.name} требует уставку, значение отсутствует",
                )
            )
            continue
        if not needs_value and event.value is not None:
            found.append(
                Violation(
                    kind=ViolationKind.UNEXPECTED_VALUE,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=f"{event.kind.name} не принимает уставку",
                )
            )
            continue
        if event.value is not None and event.value < MIN_SETPOINT_M3_PER_DAY:
            found.append(
                Violation(
                    kind=ViolationKind.NEGATIVE_SETPOINT,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name}: отрицательная уставка, допустимо "
                        f"от {MIN_SETPOINT_M3_PER_DAY} м³/сут"
                    ),
                )
            )
    return tuple(found)


def check_step_range(
    events: Sequence[CandidateEvent], n_intervals: int = N_INTERVALS
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for event in sorted(events, key=_event_sort_key):
        if event.control_step == n_intervals:
            found.append(
                Violation(
                    kind=ViolationKind.TERMINAL_STEP_HAS_CONTROL,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name} назначен на терминальный шаг "
                        f"{n_intervals}: у него нет интервала и решений он не несёт"
                    ),
                )
            )
        elif not (0 <= event.control_step < n_intervals):
            found.append(
                Violation(
                    kind=ViolationKind.STEP_OUT_OF_RANGE,
                    control_step=event.control_step,
                    well=event.well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name}: шаг вне диапазона 0…{n_intervals - 1}"
                    ),
                )
            )
    return tuple(found)


def commissioning_steps(
    fixed_deck_events: Sequence[FixedDeckEvent],
) -> dict[str, int]:
    steps: dict[str, int] = {}
    for event in fixed_deck_events:
        if event.operator not in _COMMISSIONING_OPERATORS:
            continue
        current = steps.get(event.well)
        if current is None or event.control_step < current:
            steps[event.well] = event.control_step
    return steps


def commissioning_roles(
    fixed_deck_events: Sequence[FixedDeckEvent],
) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for event in sorted(fixed_deck_events, key=lambda item: item.control_step):
        if event.operator == "WCONPROD":
            roles.setdefault(event.well, Role.PROD)
        elif event.operator == "WCONINJE":
            roles.setdefault(event.well, Role.INJ)
    return roles


def check_roles_and_conversions(
    events: Sequence[CandidateEvent],
    initial_state: Mapping[str, WellState],
    fixed_deck_events: Sequence[FixedDeckEvent] = (),
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    roles = {well: state.role for well, state in initial_state.items()}
    availability = {
        well: state.availability for well, state in initial_state.items()
    }
    commissioned_at = commissioning_steps(fixed_deck_events)
    commissioned_roles = commissioning_roles(fixed_deck_events)
    conversion_steps = {
        (event.control_step, event.well)
        for event in events
        if event.kind is EventKind.CONVERT_INJ
    }
    converted: dict[str, int] = {}
    for event in sorted(events, key=_event_sort_key):
        well = event.well
        commissioning_step = commissioned_at.get(well)
        if (
            commissioning_step is not None
            and availability.get(well) is Availability.NOT_COMMISSIONED
            and event.control_step >= commissioning_step
        ):
            availability[well] = Availability.AVAILABLE
            roles[well] = commissioned_roles.get(well, roles.get(well, Role.NONE))
        if well not in initial_state:
            found.append(
                Violation(
                    kind=ViolationKind.WELL_NOT_ON_AXIS,
                    control_step=event.control_step,
                    well=well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name}: скважины нет в initial_state, "
                        f"адресовать событие некому"
                    ),
                )
            )
            continue
        if availability[well] is Availability.NOT_COMMISSIONED:
            found.append(
                Violation(
                    kind=ViolationKind.WELL_NOT_COMMISSIONED,
                    control_step=event.control_step,
                    well=well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name} адресован скважине в состоянии "
                        f"NOT_COMMISSIONED: даты ввода не наш рычаг"
                    ),
                )
            )
            continue
        role = roles[well]
        closes_producer_on_conversion = (
            event.kind is EventKind.SET_LRAT
            and event.value == 0.0
            and (event.control_step, well) in conversion_steps
        )
        if closes_producer_on_conversion:
            continue
        if event.kind is EventKind.SET_LRAT and role is Role.INJ:
            found.append(
                Violation(
                    kind=ViolationKind.SET_LRAT_ON_INJECTOR,
                    control_step=event.control_step,
                    well=well,
                    value=event.value,
                    detail="SET_LRAT адресован скважине в роли INJ",
                )
            )
        elif event.kind is EventKind.SET_RATE and role is Role.PROD:
            found.append(
                Violation(
                    kind=ViolationKind.SET_RATE_ON_PRODUCER,
                    control_step=event.control_step,
                    well=well,
                    value=event.value,
                    detail="SET_RATE адресован скважине в роли PROD",
                )
            )
        elif event.kind is EventKind.CONVERT_INJ:
            if role is Role.INJ and well not in converted:
                found.append(
                    Violation(
                        kind=ViolationKind.CONVERT_INJ_ON_INJECTOR,
                        control_step=event.control_step,
                        well=well,
                        value=None,
                        detail="CONVERT_INJ адресован скважине, уже находящейся в роли INJ",
                    )
                )
            elif well in converted:
                found.append(
                    Violation(
                        kind=ViolationKind.CONVERT_INJ_REPEATED,
                        control_step=event.control_step,
                        well=well,
                        value=None,
                        detail=(
                            f"повторный CONVERT_INJ: первый был на шаге "
                            f"{converted[well]}"
                        ),
                    )
                )
            else:
                converted[well] = event.control_step
                roles[well] = Role.INJ
    return tuple(found)


def check_conflicts(events: Sequence[CandidateEvent]) -> tuple[Violation, ...]:
    control_events = tuple(
        ControlEvent(
            control_step=event.control_step,
            well=event.well,
            kind=event.kind,
            value=event.value,
        )
        for event in events
        if _is_constructible(event)
    )
    found: list[Violation] = []
    for step, well, kind, values in find_control_conflicts(control_events):
        found.append(
            Violation(
                kind=ViolationKind.CONFLICTING_EVENTS,
                control_step=step,
                well=well,
                value=None,
                detail=(
                    f"на одном шаге несколько несовпадающих {kind.name}: "
                    f"значения {values}"
                ),
            )
        )
    return tuple(found)


def _is_constructible(event: CandidateEvent) -> bool:
    if not (0 <= event.control_step < N_INTERVALS):
        return False
    needs_value = event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE)
    if needs_value != (event.value is not None):
        return False
    if event.value is not None and event.value < 0:
        return False
    if event.kind is EventKind.SET_LRAT and event.value is not None:
        if event.value > MAX_LRAT_M3_PER_DAY:
            return False
    return True


def fixed_layer_hash(events: Sequence[FixedDeckEvent]) -> str:
    return canonical_part_hash(list(events))


def check_fixed_layer(
    events: Sequence[FixedDeckEvent], expected_hash: str | None
) -> tuple[Violation, ...]:
    if expected_hash is None:
        return ()
    actual = fixed_layer_hash(events)
    if actual == expected_hash:
        return ()
    return (
        Violation(
            kind=ViolationKind.FIXED_LAYER_CHANGED,
            control_step=None,
            well=None,
            value=None,
            detail=(
                f"фиксированный слой дека изменён: хеш {actual} против "
                f"эталонного {expected_hash}"
            ),
        ),
    )


def check_constraints(
    events: Sequence[CandidateEvent], constraints: Constraints | None
) -> tuple[Violation, ...]:
    if constraints is None:
        return ()
    found: list[Violation] = []
    for outage in constraints.well_outages:
        for event in sorted(events, key=_event_sort_key):
            if event.well != outage.well:
                continue
            if not (outage.control_step_from <= event.control_step <= outage.control_step_to):
                continue
            if event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE) and event.value:
                found.append(
                    Violation(
                        kind=ViolationKind.WELL_OUTAGE_VIOLATED,
                        control_step=event.control_step,
                        well=event.well,
                        value=event.value,
                        detail=(
                            f"{event.kind.name} с положительной уставкой внутри "
                            f"окна простоя {outage.control_step_from}…"
                            f"{outage.control_step_to}"
                        ),
                    )
                )
            elif event.kind is EventKind.OPEN:
                found.append(
                    Violation(
                        kind=ViolationKind.WELL_OUTAGE_VIOLATED,
                        control_step=event.control_step,
                        well=event.well,
                        value=None,
                        detail=(
                            f"OPEN внутри окна простоя "
                            f"{outage.control_step_from}…{outage.control_step_to}"
                        ),
                    )
                )
    return tuple(found)


def validate_static(
    schedule: Schedule,
    constraints: Constraints | None = None,
    expected_fixed_events_hash: str | None = None,
    candidate_events: Sequence[ControlEvent | CandidateEvent] | None = None,
) -> ValidationReport:
    events = (
        candidates(candidate_events)
        if candidate_events is not None
        else candidates(schedule.control_events)
    )
    n_intervals = schedule.meta.n_intervals
    violations: list[Violation] = []
    violations.extend(check_step_range(events, n_intervals))
    violations.extend(check_setpoint_ranges(events))
    violations.extend(check_lrat_ceiling(events))
    violations.extend(
        check_roles_and_conversions(
            events, schedule.initial_state, schedule.fixed_deck_events
        )
    )
    violations.extend(check_conflicts(events))
    violations.extend(
        check_fixed_layer(schedule.fixed_deck_events, expected_fixed_events_hash)
    )
    violations.extend(check_constraints(events, constraints))
    violations.sort(
        key=lambda item: (
            -1 if item.control_step is None else item.control_step,
            _well_sort_key(item.well) if item.well is not None else (2, 0, ""),
            item.kind.value,
        )
    )
    return ValidationReport(
        violations=tuple(violations),
        n_control_events=len(events),
        n_fixed_events=len(schedule.fixed_deck_events),
        n_intervals=n_intervals,
    )
