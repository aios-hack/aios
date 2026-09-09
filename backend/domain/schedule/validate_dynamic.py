from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from backend.core.contracts import (
    MATERIAL_BALANCE_RELATIVE_TOLERANCE,
    ActiveControlMode,
    Availability,
    CompensationPolicy,
    Constraints,
    ControlEvent,
    EventKind,
    Groups,
    IntervalResponse,
    N_INTERVALS,
    OperatingStatus,
    Role,
    Schedule,
    StateAtDate,
    WellState,
    compensation_policy,
    is_excluded_by_negative_rule,
    water_supply_policy,
)
from backend.core.contracts.constraints import (
    BHP_INJECTOR_MAX_BAR,
    BHP_PRODUCER_MIN_BAR,
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    COMPENSATION_SCOPE,
    DEFAULT_BHP_INJECTOR_MAX_BAR,
    DEFAULT_BHP_PRODUCER_MIN_BAR,
    EXTERNAL_WATER_M3_PER_DAY,
    PRESSURE_CEILING_BAR,
    PRESSURE_FLOOR_BAR,
    WATER_REINJECTION_FRACTION,
    WATER_REINJECTION_LAG_STEPS,
    WATER_SUPPLY_UNLIMITED,
    FieldPressureLimits,
    bhp_limits,
    field_pressure_limits,
    limit_origin,
)
from backend.core.contracts.response import N_DECK_DATES

from .validate import (
    CONSTRAINT_WELL_OUTAGES_STATIC,
    STATUS_CHECKED,
    STATUS_NOT_SET,
    STATUS_UNSUPPORTED,
    STATUS_WAIVED,
    CONSTRAINT_COMPENSATION,
    CONSTRAINT_COMPENSATION_SCOPE,
    CONSTRAINT_INJECTION_LIMITS,
    CONSTRAINT_LIQUID_LIMITS,
    CONSTRAINT_OIL_LIMITS,
    CONSTRAINT_PRODUCTION_FLOORS,
    CONSTRAINT_WATER_SUPPLY,
    CONSTRAINT_WATERCUT_LIMITS,
    CONSTRAINT_WELL_OUTAGES,
    CONSTRAINT_BHP_LIMITS,
    CONSTRAINT_FIELD_PRESSURE,
    CONSTRAINT_MATERIAL_BALANCE,
    ConstraintCheck,
    ValidationReport,
    Violation,
    ViolationKind,
    _well_sort_key,
    candidates,
    check_constraints,
)

COMPENSATION_FIELD_SCOPES: frozenset[str] = frozenset(
    {"field", "field_and_groups"}
)
COMPENSATION_GROUP_SCOPES: frozenset[str] = frozenset(
    {"groups", "field_and_groups"}
)

PRODUCER_MIN_BHP_BAR: float = DEFAULT_BHP_PRODUCER_MIN_BAR
INJECTOR_MAX_BHP_BAR: float = DEFAULT_BHP_INJECTOR_MAX_BAR
ACHIEVEMENT_THRESHOLD: float = 0.999
FIRST_CONTROL_DECK_DATE_INDEX: int = N_DECK_DATES - N_INTERVALS - 1
FIRST_CONTROL_LEVEL_DECK_DATE_INDEX: int = FIRST_CONTROL_DECK_DATE_INDEX + 1


@dataclass(frozen=True, slots=True)
class FieldSeries:
    field_pressure_bar: tuple[float, ...]
    oil_produced_cum_m3: tuple[float, ...] = ()
    water_produced_cum_m3: tuple[float, ...] = ()
    water_injected_cum_m3: tuple[float, ...] = ()
    oil_in_place_m3: tuple[float, ...] = ()
    water_in_place_m3: tuple[float, ...] = ()

    @property
    def has_material_balance(self) -> bool:
        return bool(
            self.oil_produced_cum_m3
            and self.water_produced_cum_m3
            and self.water_injected_cum_m3
            and self.oil_in_place_m3
            and self.water_in_place_m3
        )


def level_deck_date_index(control_step: int) -> int:
    return FIRST_CONTROL_LEVEL_DECK_DATE_INDEX + control_step


def control_step_of_level(deck_date_index: int) -> int:
    return deck_date_index - FIRST_CONTROL_LEVEL_DECK_DATE_INDEX


DYNAMIC_VIOLATION_KINDS: frozenset[ViolationKind] = frozenset(
    {
        ViolationKind.TARGET_UNDERSHOOT,
        ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
        ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
        ViolationKind.MODE_NOT_REPORTED,
        ViolationKind.MODE_CONTRADICTS_SCHEDULE,
        ViolationKind.BHP_LIMITED_WITHOUT_UNDERSHOOT,
        ViolationKind.ROLE_FACT_MISMATCH,
        ViolationKind.OPEN_WITHOUT_FLOW,
        ViolationKind.SHUT_WITH_FLOW,
        ViolationKind.NEGATIVE_INTERVAL_DELTA,
        ViolationKind.RESPONSE_AXIS_INCOMPLETE,
        ViolationKind.LIQUID_LIMIT_EXCEEDED,
        ViolationKind.INJECTION_LIMIT_EXCEEDED,
        ViolationKind.PRODUCTION_FLOOR_MISSED,
        ViolationKind.OIL_LIMIT_EXCEEDED,
        ViolationKind.WATERCUT_LIMIT_EXCEEDED,
        ViolationKind.OUTAGE_WELL_PRODUCED,
        ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED,
        ViolationKind.COMPENSATION_OUT_OF_CORRIDOR,
        ViolationKind.COMPENSATION_UNDEFINED,
        ViolationKind.FIELD_PRESSURE_BELOW_FLOOR,
        ViolationKind.FIELD_PRESSURE_ABOVE_CEILING,
        ViolationKind.MATERIAL_BALANCE_BROKEN,
    }
)

BLOCKING_DYNAMIC_VIOLATION_KINDS: frozenset[ViolationKind] = frozenset(
    {
        ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
        ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
        ViolationKind.ROLE_FACT_MISMATCH,
        ViolationKind.SHUT_WITH_FLOW,
        ViolationKind.RESPONSE_AXIS_INCOMPLETE,
        ViolationKind.LIQUID_LIMIT_EXCEEDED,
        ViolationKind.INJECTION_LIMIT_EXCEEDED,
        ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED,
        ViolationKind.PRODUCTION_FLOOR_MISSED,
        ViolationKind.OIL_LIMIT_EXCEEDED,
        ViolationKind.WATERCUT_LIMIT_EXCEEDED,
        ViolationKind.OUTAGE_WELL_PRODUCED,
        ViolationKind.FIELD_PRESSURE_BELOW_FLOOR,
        ViolationKind.FIELD_PRESSURE_ABOVE_CEILING,
    }
)


def blocking_dynamic_violation_kinds(
    constraints: Constraints | None = None,
) -> frozenset[ViolationKind]:
    if constraints is None:
        return BLOCKING_DYNAMIC_VIOLATION_KINDS
    policy = compensation_policy(constraints)
    return blocking_kinds_for_compensation(policy)


def blocking_kinds_for_compensation(
    policy: CompensationPolicy,
) -> frozenset[ViolationKind]:
    if not (policy.enabled and policy.hard):
        return BLOCKING_DYNAMIC_VIOLATION_KINDS
    return BLOCKING_DYNAMIC_VIOLATION_KINDS | {
        ViolationKind.COMPENSATION_OUT_OF_CORRIDOR,
        ViolationKind.COMPENSATION_UNDEFINED,
    }


def ordered_violation_kinds(
    kinds: frozenset[ViolationKind] | Iterable[ViolationKind],
) -> tuple[ViolationKind, ...]:
    return tuple(sorted(kinds, key=lambda kind: kind.value))


@dataclass(frozen=True, slots=True)
class TargetRatio:
    control_step: int
    well: str
    role: Role
    target: float
    actual: float
    mode: ActiveControlMode

    @property
    def ratio(self) -> float:
        return self.actual / self.target

    @property
    def achieved(self) -> bool:
        return self.ratio >= ACHIEVEMENT_THRESHOLD


@dataclass(frozen=True, slots=True)
class DynamicReport:
    report: ValidationReport
    ratios: tuple[TargetRatio, ...]
    n_states: int
    n_intervals_seen: int
    n_wells: int
    blocking_kinds: tuple[ViolationKind, ...] = ordered_violation_kinds(
        BLOCKING_DYNAMIC_VIOLATION_KINDS
    )
    constraint_checks: tuple[ConstraintCheck, ...] = ()

    @property
    def ok(self) -> bool:
        return self.report.ok

    @property
    def blocking_violations(self) -> tuple[Violation, ...]:
        return tuple(
            item
            for item in self.report.violations
            if item.kind in self.blocking_kinds
        )

    @property
    def blocking_ok(self) -> bool:
        return not self.blocking_violations

    @property
    def violations(self) -> tuple[Violation, ...]:
        return self.report.violations

    def counts(self) -> dict[ViolationKind, int]:
        return self.report.counts()

    def by_kind(self) -> dict[ViolationKind, tuple[Violation, ...]]:
        return self.report.by_kind()

    def format(self, limit: int = 50) -> str:
        return self.report.format(limit)

    def undershooting(self) -> tuple[TargetRatio, ...]:
        return tuple(item for item in self.ratios if not item.achieved)

    def modes(self) -> dict[ActiveControlMode, int]:
        counts: dict[ActiveControlMode, int] = {}
        for item in self.ratios:
            counts[item.mode] = counts.get(item.mode, 0) + 1
        return counts

    def raise_if_violated(self) -> None:
        if not self.ok:
            raise DynamicValidationError(self.format(), self)


class DynamicValidationError(ValueError):
    def __init__(self, message: str, report: DynamicReport) -> None:
        super().__init__(message)
        self.report = report


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


def check_target_ratio(
    schedule: Schedule,
    states: Sequence[StateAtDate],
) -> tuple[tuple[Violation, ...], tuple[TargetRatio, ...]]:
    timelines = _target_timeline(schedule)
    indexed = _states_by_step(states)
    found: list[Violation] = []
    ratios: list[TargetRatio] = []
    for (control_step, well), state in sorted(
        indexed.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        timeline = timelines.get(well)
        if timeline is None:
            continue
        target = _target_at(timeline, control_step)
        if not target.commissioned:
            continue
        if target.operating_status is OperatingStatus.SHUT:
            continue
        if target.setpoint <= 0.0:
            continue
        actual = (
            state.injection_rate if target.role is Role.INJ else state.liquid_rate
        )
        ratio = TargetRatio(
            control_step=control_step,
            well=well,
            role=target.role,
            target=target.setpoint,
            actual=actual,
            mode=state.active_control_mode,
        )
        ratios.append(ratio)
        if not ratio.achieved:
            found.append(
                Violation(
                    kind=ViolationKind.TARGET_UNDERSHOOT,
                    control_step=control_step,
                    well=well,
                    value=ratio.ratio,
                    detail=(
                        f"факт/цель {ratio.ratio:.4f} < {ACHIEVEMENT_THRESHOLD}: "
                        f"факт {actual} м³/сут при цели {target.setpoint} м³/сут, "
                        f"режим контроля {state.active_control_mode.value}"
                    ),
                )
            )
    return tuple(found), tuple(ratios)


def bhp_constraint_check(
    constraints: Constraints | None, found: Sequence[Violation]
) -> ConstraintCheck:
    case = constraints if constraints is not None else Constraints()
    limits = bhp_limits(case)
    return _checked(
        CONSTRAINT_BHP_LIMITS,
        found,
        (
            f"коридор забойного давления {limits.producer_min_bar}…"
            f"{limits.injector_max_bar} бар: нижний предел добывающих "
            f"infrastructure.{BHP_PRODUCER_MIN_BAR}, "
            f"{limit_origin(case, BHP_PRODUCER_MIN_BAR)}; верхний предел "
            f"нагнетательных infrastructure.{BHP_INJECTOR_MAX_BAR}, "
            f"{limit_origin(case, BHP_INJECTOR_MAX_BAR)}"
        ),
        blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
    )


def check_bhp_limits(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    constraints: Constraints | None = None,
    producer_min_bar: float | None = None,
    injector_max_bar: float | None = None,
) -> tuple[Violation, ...]:
    case = constraints if constraints is not None else Constraints()
    limits = bhp_limits(case)
    if producer_min_bar is None:
        producer_min_bar = limits.producer_min_bar
    if injector_max_bar is None:
        injector_max_bar = limits.injector_max_bar
    producer_origin = limit_origin(case, BHP_PRODUCER_MIN_BAR)
    injector_origin = limit_origin(case, BHP_INJECTOR_MAX_BAR)
    timelines = _target_timeline(schedule)
    indexed = _states_by_step(states)
    found: list[Violation] = []
    for (control_step, well), state in sorted(
        indexed.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        timeline = timelines.get(well)
        if timeline is None:
            continue
        target = _target_at(timeline, control_step)
        if not target.commissioned:
            continue
        if state.active_control_mode in (
            ActiveControlMode.SHUT,
            ActiveControlMode.NOT_COMMISSIONED,
        ):
            continue
        if target.role is Role.INJ:
            if state.bhp > injector_max_bar:
                found.append(
                    Violation(
                        kind=ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
                        control_step=control_step,
                        well=well,
                        value=state.bhp,
                        detail=(
                            f"забойное давление нагнетательной {state.bhp} бар "
                            f"выше предела {injector_max_bar} бар; предел "
                            f"infrastructure.{BHP_INJECTOR_MAX_BAR}, "
                            f"{injector_origin}"
                        ),
                    )
                )
        elif target.role is Role.PROD:
            if state.liquid_rate <= 0.0:
                continue
            if state.bhp < producer_min_bar:
                found.append(
                    Violation(
                        kind=ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
                        control_step=control_step,
                        well=well,
                        value=state.bhp,
                        detail=(
                            f"забойное давление добывающей {state.bhp} бар "
                            f"ниже предела {producer_min_bar} бар; предел "
                            f"infrastructure.{BHP_PRODUCER_MIN_BAR}, "
                            f"{producer_origin}"
                        ),
                    )
                )
    return tuple(found)


def check_control_modes(
    schedule: Schedule,
    states: Sequence[StateAtDate],
) -> tuple[Violation, ...]:
    timelines = _target_timeline(schedule)
    indexed = _states_by_step(states)
    found: list[Violation] = []
    for (control_step, well), state in sorted(
        indexed.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        timeline = timelines.get(well)
        if timeline is None:
            continue
        target = _target_at(timeline, control_step)
        mode = state.active_control_mode
        if mode is ActiveControlMode.UNKNOWN:
            found.append(
                Violation(
                    kind=ViolationKind.MODE_NOT_REPORTED,
                    control_step=control_step,
                    well=well,
                    value=None,
                    detail=(
                        "active_control_mode = UNKNOWN: режим контроля не "
                        "предъявлен, недостижимость цели необъяснима"
                    ),
                )
            )
            continue
        if not target.commissioned:
            if mode is not ActiveControlMode.NOT_COMMISSIONED:
                found.append(
                    Violation(
                        kind=ViolationKind.MODE_CONTRADICTS_SCHEDULE,
                        control_step=control_step,
                        well=well,
                        value=None,
                        detail=(
                            f"расписание держит скважину невведённой, отклик даёт "
                            f"{mode.value}"
                        ),
                    )
                )
            continue
        if mode is ActiveControlMode.NOT_COMMISSIONED:
            found.append(
                Violation(
                    kind=ViolationKind.MODE_CONTRADICTS_SCHEDULE,
                    control_step=control_step,
                    well=well,
                    value=None,
                    detail=(
                        "отклик даёт NOT_COMMISSIONED для скважины, введённой "
                        "по расписанию"
                    ),
                )
            )
            continue
        if mode is ActiveControlMode.BHP_LIMITED:
            if target.setpoint <= 0.0:
                continue
            actual = (
                state.injection_rate if target.role is Role.INJ else state.liquid_rate
            )
            if actual / target.setpoint >= ACHIEVEMENT_THRESHOLD:
                found.append(
                    Violation(
                        kind=ViolationKind.BHP_LIMITED_WITHOUT_UNDERSHOOT,
                        control_step=control_step,
                        well=well,
                        value=actual / target.setpoint,
                        detail=(
                            "режим BHP_LIMITED при достигнутой цели: предел по "
                            "давлению заявлен, а недобора нет"
                        ),
                    )
                )
    return tuple(found)


def check_role_consistency(
    schedule: Schedule,
    states: Sequence[StateAtDate],
) -> tuple[Violation, ...]:
    timelines = _target_timeline(schedule)
    indexed = _states_by_step(states)
    found: list[Violation] = []
    for (control_step, well), state in sorted(
        indexed.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        timeline = timelines.get(well)
        if timeline is None:
            continue
        target = _target_at(timeline, control_step)
        if not target.commissioned:
            continue
        if target.role is Role.INJ and state.liquid_rate > 0.0:
            found.append(
                Violation(
                    kind=ViolationKind.ROLE_FACT_MISMATCH,
                    control_step=control_step,
                    well=well,
                    value=state.liquid_rate,
                    detail=(
                        f"скважина в роли INJ даёт добычу жидкости "
                        f"{state.liquid_rate} м³/сут"
                    ),
                )
            )
        elif target.role is Role.PROD and state.injection_rate > 0.0:
            found.append(
                Violation(
                    kind=ViolationKind.ROLE_FACT_MISMATCH,
                    control_step=control_step,
                    well=well,
                    value=state.injection_rate,
                    detail=(
                        f"скважина в роли PROD даёт закачку "
                        f"{state.injection_rate} м³/сут"
                    ),
                )
            )
    return tuple(found)


def check_intent_versus_fact(
    schedule: Schedule,
    states: Sequence[StateAtDate],
) -> tuple[Violation, ...]:
    timelines = _target_timeline(schedule)
    indexed = _states_by_step(states)
    found: list[Violation] = []
    for (control_step, well), state in sorted(
        indexed.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        timeline = timelines.get(well)
        if timeline is None:
            continue
        target = _target_at(timeline, control_step)
        if not target.commissioned:
            continue
        if not target.setpoint_known:
            continue
        flowing = state.liquid_rate > 0.0 or state.injection_rate > 0.0
        wants_open = (
            target.operating_status is OperatingStatus.OPEN and target.setpoint > 0.0
        )
        if wants_open and not flowing:
            found.append(
                Violation(
                    kind=ViolationKind.OPEN_WITHOUT_FLOW,
                    control_step=control_step,
                    well=well,
                    value=target.setpoint,
                    detail=(
                        f"расписание держит скважину открытой с уставкой "
                        f"{target.setpoint} м³/сут, отклик даёт нулевой дебит; "
                        f"режим контроля {state.active_control_mode.value}"
                    ),
                )
            )
        elif not wants_open and flowing:
            found.append(
                Violation(
                    kind=ViolationKind.SHUT_WITH_FLOW,
                    control_step=control_step,
                    well=well,
                    value=max(state.liquid_rate, state.injection_rate),
                    detail=(
                        "расписание держит скважину остановленной, отклик даёт "
                        "ненулевой дебит"
                    ),
                )
            )
    return tuple(found)


def check_response_axes(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    interval_responses: Sequence[IntervalResponse],
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    wells = tuple(schedule.meta.wells)
    n_intervals = schedule.meta.n_intervals
    n_deck_dates = n_intervals + FIRST_CONTROL_DECK_DATE_INDEX + 1

    seen_states = {(state.deck_date_index, state.well) for state in states}
    expected_states = len(wells) * n_deck_dates
    if len(seen_states) != expected_states:
        found.append(
            Violation(
                kind=ViolationKind.RESPONSE_AXIS_INCOMPLETE,
                control_step=None,
                well=None,
                value=float(len(seen_states)),
                detail=(
                    f"StateAtDate: {len(seen_states)} пар (дата, скважина) при "
                    f"ожидаемых {expected_states} = {len(wells)} × {n_deck_dates}"
                ),
            )
        )

    seen_intervals = {
        (item.control_step, item.well) for item in interval_responses
    }
    expected_intervals = len(wells) * n_intervals
    if len(seen_intervals) != expected_intervals:
        found.append(
            Violation(
                kind=ViolationKind.RESPONSE_AXIS_INCOMPLETE,
                control_step=None,
                well=None,
                value=float(len(seen_intervals)),
                detail=(
                    f"IntervalResponse: {len(seen_intervals)} пар (шаг, скважина) "
                    f"при ожидаемых {expected_intervals} = {len(wells)} × "
                    f"{n_intervals}"
                ),
            )
        )
    return tuple(found)


def check_interval_signs(
    interval_responses: Sequence[IntervalResponse],
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for item in sorted(
        interval_responses,
        key=lambda entry: (entry.control_step, _well_sort_key(entry.well)),
    ):
        if not is_excluded_by_negative_rule(item):
            continue
        found.append(
            Violation(
                kind=ViolationKind.NEGATIVE_INTERVAL_DELTA,
                control_step=item.control_step,
                well=item.well,
                value=min(
                    item.liquid_volume_delta,
                    item.oil_mass_delta,
                    item.injection_volume_delta,
                ),
                detail=(
                    "отрицательный месячный прирост: накопленные величины "
                    "симулятора обязаны быть монотонны"
                ),
            )
        )
    return tuple(found)


def year_of_step(schedule: Schedule, control_step: int) -> int:
    t0 = schedule.meta.t0
    month_index = t0.month - 1 + control_step
    return t0.year + month_index // 12


def check_dynamic_constraints(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints | None,
    oil_density_t_per_m3: float | None = None,
    field_series: FieldSeries | None = None,
    groups: Groups | None = None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    if constraints is None:
        return (), _absent_constraint_checks(field_series)
    found: list[Violation] = []
    checks: list[ConstraintCheck] = []
    for violations, records in (
        _check_rate_limits(schedule, states, constraints),
        _check_watercut_limits(
            schedule, interval_responses, constraints, oil_density_t_per_m3
        ),
        _check_water_supply(
            schedule, interval_responses, constraints, oil_density_t_per_m3
        ),
        _check_outages(schedule, states, constraints),
        _check_compensation(schedule, interval_responses, constraints, groups),
        check_field_pressure(schedule, constraints, field_series),
        check_material_balance(field_series),
    ):
        found.extend(violations)
        checks.extend(records)
    return tuple(found), tuple(checks)


DYNAMIC_CONSTRAINT_NAMES: tuple[str, ...] = (
    CONSTRAINT_LIQUID_LIMITS,
    CONSTRAINT_INJECTION_LIMITS,
    CONSTRAINT_PRODUCTION_FLOORS,
    CONSTRAINT_OIL_LIMITS,
    CONSTRAINT_WATERCUT_LIMITS,
    CONSTRAINT_WATER_SUPPLY,
    CONSTRAINT_WELL_OUTAGES,
    CONSTRAINT_COMPENSATION,
    CONSTRAINT_COMPENSATION_SCOPE,
    CONSTRAINT_FIELD_PRESSURE,
    CONSTRAINT_MATERIAL_BALANCE,
)

_CONSTRAINT_KINDS: dict[str, tuple[ViolationKind, ...]] = {
    CONSTRAINT_BHP_LIMITS: (
        ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
        ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
    ),
    CONSTRAINT_LIQUID_LIMITS: (ViolationKind.LIQUID_LIMIT_EXCEEDED,),
    CONSTRAINT_INJECTION_LIMITS: (ViolationKind.INJECTION_LIMIT_EXCEEDED,),
    CONSTRAINT_PRODUCTION_FLOORS: (ViolationKind.PRODUCTION_FLOOR_MISSED,),
    CONSTRAINT_OIL_LIMITS: (ViolationKind.OIL_LIMIT_EXCEEDED,),
    CONSTRAINT_WATERCUT_LIMITS: (ViolationKind.WATERCUT_LIMIT_EXCEEDED,),
    CONSTRAINT_WATER_SUPPLY: (ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED,),
    CONSTRAINT_WELL_OUTAGES: (ViolationKind.OUTAGE_WELL_PRODUCED,),
    CONSTRAINT_COMPENSATION: (
        ViolationKind.COMPENSATION_OUT_OF_CORRIDOR,
        ViolationKind.COMPENSATION_UNDEFINED,
    ),
    CONSTRAINT_COMPENSATION_SCOPE: (
        ViolationKind.COMPENSATION_OUT_OF_CORRIDOR,
        ViolationKind.COMPENSATION_UNDEFINED,
    ),
    CONSTRAINT_FIELD_PRESSURE: (
        ViolationKind.FIELD_PRESSURE_BELOW_FLOOR,
        ViolationKind.FIELD_PRESSURE_ABOVE_CEILING,
    ),
    CONSTRAINT_MATERIAL_BALANCE: (ViolationKind.MATERIAL_BALANCE_BROKEN,),
}


def constraint_kinds(constraint: str) -> tuple[ViolationKind, ...]:
    if constraint == CONSTRAINT_WELL_OUTAGES_STATIC:
        return (ViolationKind.WELL_OUTAGE_VIOLATED,)
    if constraint not in _CONSTRAINT_KINDS:
        raise KeyError(
            f"ограничение {constraint!r} не объявлено в отчёте о проверках: "
            "виды нарушений для него неизвестны"
        )
    return _CONSTRAINT_KINDS[constraint]


CONSTRAINT_FIELD_COVERAGE: dict[str, tuple[str, ...]] = {
    "liquid_limits": (CONSTRAINT_LIQUID_LIMITS,),
    "injection_limits": (CONSTRAINT_INJECTION_LIMITS,),
    "production_floors": (CONSTRAINT_PRODUCTION_FLOORS,),
    "oil_limits": (CONSTRAINT_OIL_LIMITS,),
    "watercut_limits": (CONSTRAINT_WATERCUT_LIMITS,),
    "well_outages": (CONSTRAINT_WELL_OUTAGES, CONSTRAINT_WELL_OUTAGES_STATIC),
    WATER_SUPPLY_UNLIMITED: (CONSTRAINT_WATER_SUPPLY,),
    WATER_REINJECTION_FRACTION: (CONSTRAINT_WATER_SUPPLY,),
    WATER_REINJECTION_LAG_STEPS: (CONSTRAINT_WATER_SUPPLY,),
    EXTERNAL_WATER_M3_PER_DAY: (CONSTRAINT_WATER_SUPPLY,),
    COMPENSATION_MIN: (CONSTRAINT_COMPENSATION,),
    COMPENSATION_MAX: (CONSTRAINT_COMPENSATION,),
    COMPENSATION_ENFORCEMENT: (CONSTRAINT_COMPENSATION,),
    COMPENSATION_SCOPE: (CONSTRAINT_COMPENSATION_SCOPE,),
    BHP_PRODUCER_MIN_BAR: (CONSTRAINT_BHP_LIMITS,),
    BHP_INJECTOR_MAX_BAR: (CONSTRAINT_BHP_LIMITS,),
    PRESSURE_FLOOR_BAR: (CONSTRAINT_FIELD_PRESSURE,),
    PRESSURE_CEILING_BAR: (CONSTRAINT_FIELD_PRESSURE,),
}

PHYSICS_CONSTRAINT_NAMES: tuple[str, ...] = (CONSTRAINT_MATERIAL_BALANCE,)

PROVENANCE_FIELDS: frozenset[str] = frozenset({"infrastructure", "case_path"})


def constraint_fields_to_cover() -> tuple[str, ...]:
    fields = tuple(
        name
        for name in Constraints.__dataclass_fields__
        if name not in PROVENANCE_FIELDS
    )
    return fields + (
        WATER_SUPPLY_UNLIMITED,
        WATER_REINJECTION_FRACTION,
        WATER_REINJECTION_LAG_STEPS,
        EXTERNAL_WATER_M3_PER_DAY,
        COMPENSATION_MIN,
        COMPENSATION_MAX,
        COMPENSATION_ENFORCEMENT,
        COMPENSATION_SCOPE,
        BHP_PRODUCER_MIN_BAR,
        BHP_INJECTOR_MAX_BAR,
        PRESSURE_FLOOR_BAR,
        PRESSURE_CEILING_BAR,
    )


def verified_constraint_checks(
    checks: Sequence[ConstraintCheck],
) -> tuple[ConstraintCheck, ...]:
    present = {item.constraint for item in checks}
    if len(present) != len(checks):
        raise ValueError(
            "отчёт о применённых ограничениях содержит повторяющиеся записи: "
            "одно ограничение обязано давать ровно один статус"
        )
    missing_physics = [
        name for name in PHYSICS_CONSTRAINT_NAMES if name not in present
    ]
    if missing_physics:
        raise ValueError(
            "отчёт о применённых ограничениях не содержит записей о "
            f"физических проверках: {', '.join(sorted(missing_physics))}; "
            "проверка, не зависящая от кейса, всё равно обязана назвать "
            "свой статус"
        )
    uncovered: list[str] = []
    for field_name in constraint_fields_to_cover():
        expected = CONSTRAINT_FIELD_COVERAGE.get(field_name)
        if expected is None:
            uncovered.append(field_name)
            continue
        if not present.issuperset(expected):
            uncovered.append(field_name)
    if uncovered:
        raise ValueError(
            "отчёт о применённых ограничениях неполон, без записи остались "
            f"поля кейса: {', '.join(sorted(uncovered))}; поле, объявленное "
            "в Constraints, обязано получить статус проверки, иначе "
            "sound=true скрывает непроверенное ограничение"
        )
    return tuple(sorted(checks, key=lambda item: item.constraint))


def _not_set(
    constraint: str, detail: str, *, enforcement: str | None = None
) -> ConstraintCheck:
    return ConstraintCheck(
        constraint=constraint,
        status=STATUS_NOT_SET,
        kinds=constraint_kinds(constraint),
        n_violations=None,
        blocking=False,
        enforcement=enforcement,
        detail=detail,
    )


def _checked(
    constraint: str,
    violations: Sequence[Violation],
    detail: str,
    *,
    blocking_kinds: frozenset[ViolationKind],
    enforcement: str | None = None,
) -> ConstraintCheck:
    kinds = constraint_kinds(constraint)
    return ConstraintCheck(
        constraint=constraint,
        status=STATUS_CHECKED,
        kinds=kinds,
        n_violations=sum(1 for item in violations if item.kind in kinds),
        blocking=any(kind in blocking_kinds for kind in kinds),
        enforcement=enforcement,
        detail=detail,
    )


def _absent_constraint_checks(
    field_series: FieldSeries | None = None,
) -> tuple[ConstraintCheck, ...]:
    detail = "ограничения кейса не переданы: динамические проверки не запускались"
    names = tuple(
        name for name in DYNAMIC_CONSTRAINT_NAMES
        if name != CONSTRAINT_MATERIAL_BALANCE
    )
    _, balance_checks = check_material_balance(field_series)
    return tuple(_not_set(name, detail) for name in names) + balance_checks


def _compensation_totals(
    interval_responses: Sequence[IntervalResponse],
) -> dict[int, tuple[float, float]]:
    totals: dict[int, tuple[float, float]] = {}
    for item in interval_responses:
        withdrawal, injection = totals.get(item.control_step, (0.0, 0.0))
        totals[item.control_step] = (
            withdrawal + max(0.0, item.liquid_volume_delta),
            injection + max(0.0, item.injection_volume_delta),
        )
    return totals


def _group_membership(groups: Groups) -> dict[str, tuple[str, ...]]:
    membership: dict[str, list[str]] = {}
    for group_id in sorted(groups.groups):
        for well in groups.groups[group_id]:
            membership.setdefault(well, []).append(group_id)
    return {well: tuple(ids) for well, ids in membership.items()}


def _compensation_group_totals(
    interval_responses: Sequence[IntervalResponse], groups: Groups
) -> dict[tuple[int, str], tuple[float, float]]:
    membership = _group_membership(groups)
    uncovered = sorted(
        {item.well for item in interval_responses if item.well not in membership}
    )
    if uncovered:
        raise ValueError(
            "групповая компенсация требует, чтобы каждая скважина отклика "
            f"принадлежала участку, вне участков остались: {', '.join(uncovered)}; "
            "считать C(k) по неполной нарезке значит объявить проверку "
            "выполненной там, где часть отбора и закачки не учтена"
        )
    totals: dict[tuple[int, str], tuple[float, float]] = {}
    for item in interval_responses:
        for group_id in membership[item.well]:
            key = (item.control_step, group_id)
            withdrawal, injection = totals.get(key, (0.0, 0.0))
            totals[key] = (
                withdrawal + max(0.0, item.liquid_volume_delta),
                injection + max(0.0, item.injection_volume_delta),
            )
    return totals


def _compensation_violation(
    control_step: int,
    withdrawal: float,
    injection: float,
    minimum: float,
    maximum: float,
    source: str,
    where: str,
) -> Violation | None:
    if withdrawal <= 0.0:
        return Violation(
            kind=ViolationKind.COMPENSATION_UNDEFINED,
            control_step=control_step,
            well=None,
            value=injection,
            detail=(
                f"шаг {control_step}, {where}: отбор жидкости за шаг равен "
                f"{withdrawal:.6f} м³, компенсация C(k) = закачка / отбор "
                f"не определена и в коридор {minimum}…{maximum} "
                f"не проверялась; закачано {injection:.3f} м³; "
                f"границы: {source}"
            ),
        )
    value = injection / withdrawal
    if minimum <= value <= maximum:
        return None
    side = "ниже нижней" if value < minimum else "выше верхней"
    return Violation(
        kind=ViolationKind.COMPENSATION_OUT_OF_CORRIDOR,
        control_step=control_step,
        well=None,
        value=value,
        detail=(
            f"шаг {control_step}, {where}: компенсация C(k) = {value:.4f} "
            f"{side} границы коридора {minimum}…{maximum}; "
            f"закачано {injection:.3f} м³ при отборе жидкости "
            f"{withdrawal:.3f} м³; границы: {source}"
        ),
    )


def _compensation_disabled_checks(
    policy: CompensationPolicy,
) -> tuple[ConstraintCheck, ...]:
    return (
        _not_set(
            CONSTRAINT_COMPENSATION,
            (
                f"infrastructure.{COMPENSATION_MIN}/{COMPENSATION_MAX} "
                "не заданы: коридор компенсации C(k) не проверялся"
            ),
            enforcement=policy.enforcement,
        ),
        _not_set(
            CONSTRAINT_COMPENSATION_SCOPE,
            (
                f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}, но "
                "коридор выключен: область проверки применять не к чему"
            ),
            enforcement=policy.enforcement,
        ),
    )


def _compensation_field_check(
    schedule: Schedule,
    totals: Mapping[int, tuple[float, float]],
    policy: CompensationPolicy,
    minimum: float,
    maximum: float,
    source: str,
) -> tuple[tuple[Violation, ...], ConstraintCheck]:
    if policy.scope not in COMPENSATION_FIELD_SCOPES:
        return (), _not_set(
            CONSTRAINT_COMPENSATION,
            (
                f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}: кейс "
                "требует коридор только по участкам, разрез по полю целиком "
                "не запрашивался"
            ),
            enforcement=policy.enforcement,
        )
    found: list[Violation] = []
    for control_step in range(schedule.meta.n_intervals):
        if control_step not in totals:
            continue
        withdrawal, injection = totals[control_step]
        violation = _compensation_violation(
            control_step,
            withdrawal,
            injection,
            minimum,
            maximum,
            source,
            "поле целиком",
        )
        if violation is not None:
            found.append(violation)
    return tuple(found), _checked(
        CONSTRAINT_COMPENSATION,
        found,
        (
            f"коридор компенсации {minimum}…{maximum}, режим "
            f"{policy.enforcement}: C(k) = закачка / отбор проверена по полю "
            f"на {len(totals)} шагах"
        ),
        blocking_kinds=blocking_kinds_for_compensation(policy),
        enforcement=policy.enforcement,
    )


def _compensation_groups_check(
    schedule: Schedule,
    interval_responses: Sequence[IntervalResponse],
    groups: Groups | None,
    policy: CompensationPolicy,
    minimum: float,
    maximum: float,
    source: str,
) -> tuple[tuple[Violation, ...], ConstraintCheck]:
    if policy.scope not in COMPENSATION_GROUP_SCOPES:
        return (), _checked(
            CONSTRAINT_COMPENSATION_SCOPE,
            (),
            (
                f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}: кейс "
                "требует коридор только по полю целиком, групповой разрез "
                "не запрашивался"
            ),
            blocking_kinds=frozenset(),
            enforcement=policy.enforcement,
        )
    if groups is None:
        raise ValueError(
            f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r} требует "
            "нарезки фонда на участки, но Groups в валидатор не переданы: "
            "групповой коридор C(k) объявлен кейсом и обязан быть посчитан. "
            "Пропустить его значит выдать sound=true по ограничению, которое "
            "никто не проверял"
        )
    totals = _compensation_group_totals(interval_responses, groups)
    found: list[Violation] = []
    for control_step in range(schedule.meta.n_intervals):
        for group_id in sorted(groups.groups):
            key = (control_step, group_id)
            if key not in totals:
                continue
            withdrawal, injection = totals[key]
            violation = _compensation_violation(
                control_step,
                withdrawal,
                injection,
                minimum,
                maximum,
                source,
                f"участок {group_id}",
            )
            if violation is not None:
                found.append(violation)
    blocking_kinds = blocking_kinds_for_compensation(policy)
    kinds = constraint_kinds(CONSTRAINT_COMPENSATION_SCOPE)
    return tuple(found), ConstraintCheck(
        constraint=CONSTRAINT_COMPENSATION_SCOPE,
        status=STATUS_CHECKED,
        kinds=kinds,
        n_violations=len(found),
        blocking=any(kind in blocking_kinds for kind in kinds),
        enforcement=policy.enforcement,
        detail=(
            f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}: коридор "
            f"{minimum}…{maximum} проверен по участкам, нарезка "
            f"{groups.group_hash} из {len(groups.groups)} участков, "
            f"{len(totals)} пар шаг-участок"
        ),
    )


def _check_compensation(
    schedule: Schedule,
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints,
    groups: Groups | None = None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    policy = compensation_policy(constraints)
    if not policy.enabled:
        return (), _compensation_disabled_checks(policy)
    minimum = policy.minimum
    maximum = policy.maximum
    if minimum is None or maximum is None:
        raise ValueError(
            "коридор компенсации объявлен включённым, но границы не заданы: "
            "C(k) не с чем сравнивать"
        )
    source = (
        f"infrastructure.{COMPENSATION_MIN}/{COMPENSATION_MAX}, "
        f"режим {policy.enforcement}, {limit_origin(constraints, COMPENSATION_MIN)}"
    )
    field_found, field_check = _compensation_field_check(
        schedule,
        _compensation_totals(interval_responses),
        policy,
        minimum,
        maximum,
        source,
    )
    group_found, group_check = _compensation_groups_check(
        schedule,
        interval_responses,
        groups,
        policy,
        minimum,
        maximum,
        source,
    )
    return field_found + group_found, (field_check, group_check)


def _days_in_step(schedule: Schedule, control_step: int) -> int:
    month_index = schedule.meta.t0.month - 1 + control_step
    year = schedule.meta.t0.year + month_index // 12
    month = month_index % 12 + 1
    return monthrange(year, month)[1]


def _check_water_supply(
    schedule: Schedule,
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints,
    oil_density_t_per_m3: float | None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    policy = water_supply_policy(constraints)
    if policy.unlimited:
        return (), (
            ConstraintCheck(
                constraint=CONSTRAINT_WATER_SUPPLY,
                status=STATUS_WAIVED,
                kinds=constraint_kinds(CONSTRAINT_WATER_SUPPLY),
                n_violations=None,
                blocking=False,
                enforcement=None,
                detail=(
                    f"infrastructure.{WATER_SUPPLY_UNLIMITED} = true: кейс "
                    "объявил источник воды неограниченным, материальный баланс "
                    "воды снят явно, а не пропущен"
                ),
            ),
        )
    if not policy.enabled:
        return (), (
            _not_set(
                CONSTRAINT_WATER_SUPPLY,
                (
                    f"ни {WATER_REINJECTION_FRACTION}, ни "
                    f"{WATER_REINJECTION_LAG_STEPS}, ни "
                    f"{EXTERNAL_WATER_M3_PER_DAY} в infrastructure не заданы: "
                    "материальный баланс воды не проверялся"
                ),
            ),
        )
    if oil_density_t_per_m3 is None or oil_density_t_per_m3 <= 0.0:
        raise ValueError(
            "water_reinjection_fraction задан, но положительная плотность "
            "нефти не передана: объём добытой воды не определён"
        )

    totals: dict[int, tuple[float, float, float]] = {}
    for item in interval_responses:
        oil, liquid, injection = totals.get(item.control_step, (0.0, 0.0, 0.0))
        totals[item.control_step] = (
            oil + max(0.0, item.oil_mass_delta),
            liquid + max(0.0, item.liquid_volume_delta),
            injection + max(0.0, item.injection_volume_delta),
        )
    produced_water = {
        step: max(0.0, liquid - oil / oil_density_t_per_m3)
        for step, (oil, liquid, _) in totals.items()
    }
    origin = limit_origin(constraints, WATER_REINJECTION_FRACTION)
    found: list[Violation] = []
    for control_step in range(schedule.meta.n_intervals):
        injection = totals.get(control_step, (0.0, 0.0, 0.0))[2]
        source_step = control_step - policy.lag_steps
        source_water = produced_water.get(source_step, 0.0)
        available = (
            policy.external_water_m3_per_day
            * _days_in_step(schedule, control_step)
            + float(policy.reinjection_fraction or 0.0) * source_water
        )
        if injection <= available + 1.0e-6:
            continue
        found.append(
            Violation(
                kind=ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED,
                control_step=control_step,
                well=None,
                value=injection,
                detail=(
                    f"закачано {injection:.3f} м³ при доступном материальном "
                    f"балансе воды {available:.3f} м³; источник: "
                    f"{policy.reinjection_fraction} × добытая вода шага "
                    f"{source_step} + {policy.external_water_m3_per_day} м³/сут; "
                    f"предел infrastructure.{WATER_REINJECTION_FRACTION}, "
                    f"{origin}"
                ),
            )
        )
    return tuple(found), (
        _checked(
            CONSTRAINT_WATER_SUPPLY,
            found,
            (
                f"доля возврата {policy.reinjection_fraction}, лаг "
                f"{policy.lag_steps} шагов, внешний приток "
                f"{policy.external_water_m3_per_day} м³/сут: закачка сверена "
                f"с балансом воды на {schedule.meta.n_intervals} шагах"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


def _pressure_source(constraints: Constraints, limits: FieldPressureLimits) -> str:
    parts: list[str] = []
    if limits.floor_bar is not None:
        parts.append(
            f"пол infrastructure.{PRESSURE_FLOOR_BAR} = {limits.floor_bar} бар, "
            f"{limit_origin(constraints, PRESSURE_FLOOR_BAR)}"
        )
    if limits.ceiling_bar is not None:
        parts.append(
            f"потолок infrastructure.{PRESSURE_CEILING_BAR} = "
            f"{limits.ceiling_bar} бар, "
            f"{limit_origin(constraints, PRESSURE_CEILING_BAR)}"
        )
    return "; ".join(parts)


def check_field_pressure(
    schedule: Schedule,
    constraints: Constraints,
    field_series: FieldSeries | None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    limits = field_pressure_limits(constraints)
    if not limits.enabled:
        return (), (
            _not_set(
                CONSTRAINT_FIELD_PRESSURE,
                (
                    f"ни infrastructure.{PRESSURE_FLOOR_BAR}, ни "
                    f"infrastructure.{PRESSURE_CEILING_BAR} в кейсе не заданы: "
                    "пластовое давление не проверялось, предел назначать "
                    "за организаторов нельзя"
                ),
            ),
        )
    if field_series is None:
        raise ValueError(
            f"infrastructure.{PRESSURE_FLOOR_BAR}/{PRESSURE_CEILING_BAR} "
            "заданы, но серия пластового давления не передана: политика "
            "давления включена, а проверять нечего. Давление известно только "
            "после прогона OPM, поэтому валидатор обязан получить FPR "
            "или сообщить об ошибке, а не признать расписание допустимым"
        )
    pressures = field_series.field_pressure_bar
    if not pressures:
        raise ValueError(
            f"infrastructure.{PRESSURE_FLOOR_BAR}/{PRESSURE_CEILING_BAR} "
            "заданы, но серия FPR пуста: сравнивать с пределом нечего"
        )
    n_intervals = schedule.meta.n_intervals
    required = level_deck_date_index(n_intervals - 1) + 1
    if len(pressures) < required:
        raise ValueError(
            f"серия FPR короче горизонта: {len(pressures)} значений при "
            f"необходимых {required} = {FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + "
            f"{n_intervals}; уровень давления шага управления "
            f"{n_intervals - 1} читается по индексу дека "
            f"{level_deck_date_index(n_intervals - 1)}"
        )
    source = _pressure_source(constraints, limits)
    found: list[Violation] = []
    for control_step in range(n_intervals):
        value = pressures[level_deck_date_index(control_step)]
        if limits.floor_bar is not None and value < limits.floor_bar:
            found.append(
                Violation(
                    kind=ViolationKind.FIELD_PRESSURE_BELOW_FLOOR,
                    control_step=control_step,
                    well=None,
                    value=value,
                    detail=(
                        f"среднее пластовое давление {value:.3f} бар ниже пола "
                        f"{limits.floor_bar} бар; {source}"
                    ),
                )
            )
        if limits.ceiling_bar is not None and value > limits.ceiling_bar:
            found.append(
                Violation(
                    kind=ViolationKind.FIELD_PRESSURE_ABOVE_CEILING,
                    control_step=control_step,
                    well=None,
                    value=value,
                    detail=(
                        f"среднее пластовое давление {value:.3f} бар выше "
                        f"потолка {limits.ceiling_bar} бар; {source}"
                    ),
                )
            )
    return tuple(found), (
        _checked(
            CONSTRAINT_FIELD_PRESSURE,
            found,
            (
                f"пластовое давление сверено на {n_intervals} шагах управления "
                f"по FPR, уровень шага k читается по индексу дека "
                f"{FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + k; {source}"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


def _relative_error(delta_stock: float, delta_flow: float) -> float:
    denom = abs(delta_flow)
    return 0.0 if denom == 0.0 else abs(delta_stock - delta_flow) / denom


def check_material_balance(
    field_series: FieldSeries | None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    if field_series is None or not field_series.has_material_balance:
        return (), (
            _not_set(
                CONSTRAINT_MATERIAL_BALANCE,
                (
                    "полевые серии FOIP/FWIP/FOPT/FWPT/FWIT не переданы: "
                    "материальный баланс пласта не проверялся"
                ),
            ),
        )
    oil_stock = (
        field_series.oil_in_place_m3[-1] - field_series.oil_in_place_m3[0]
    )
    oil_flow = (
        field_series.oil_produced_cum_m3[-1]
        - field_series.oil_produced_cum_m3[0]
    )
    water_stock = (
        field_series.water_in_place_m3[-1] - field_series.water_in_place_m3[0]
    )
    water_injected = (
        field_series.water_injected_cum_m3[-1]
        - field_series.water_injected_cum_m3[0]
    )
    water_produced = (
        field_series.water_produced_cum_m3[-1]
        - field_series.water_produced_cum_m3[0]
    )
    oil_error = _relative_error(oil_stock, -oil_flow)
    water_error = _relative_error(water_stock, water_injected - water_produced)
    found: list[Violation] = []
    if oil_error > MATERIAL_BALANCE_RELATIVE_TOLERANCE:
        found.append(
            Violation(
                kind=ViolationKind.MATERIAL_BALANCE_BROKEN,
                control_step=None,
                well=None,
                value=oil_error,
                detail=(
                    f"баланс нефти по горизонту не сходится: относительная "
                    f"невязка {oil_error:.6f} выше допуска "
                    f"{MATERIAL_BALANCE_RELATIVE_TOLERANCE}; изменение запаса "
                    f"{oil_stock:.3f} м³ против добытого {oil_flow:.3f} м³"
                ),
            )
        )
    if water_error > MATERIAL_BALANCE_RELATIVE_TOLERANCE:
        found.append(
            Violation(
                kind=ViolationKind.MATERIAL_BALANCE_BROKEN,
                control_step=None,
                well=None,
                value=water_error,
                detail=(
                    f"баланс воды по горизонту не сходится: относительная "
                    f"невязка {water_error:.6f} выше допуска "
                    f"{MATERIAL_BALANCE_RELATIVE_TOLERANCE}; изменение запаса "
                    f"{water_stock:.3f} м³ против закачанного минус добытого "
                    f"{water_injected - water_produced:.3f} м³"
                ),
            )
        )
    return tuple(found), (
        _checked(
            CONSTRAINT_MATERIAL_BALANCE,
            found,
            (
                f"материальный баланс сверен по горизонту при допуске "
                f"{MATERIAL_BALANCE_RELATIVE_TOLERANCE}: невязка по нефти "
                f"{oil_error:.6f}, по воде {water_error:.6f}"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


def _check_rate_limits(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    constraints: Constraints,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    empty = not (
        constraints.liquid_limits
        or constraints.injection_limits
        or constraints.production_floors
        or constraints.oil_limits
    )
    if empty:
        return (), _rate_limit_checks(constraints, ())
    totals: dict[int, tuple[float, float, float]] = {}
    for state in states:
        control_step = state.deck_date_index - FIRST_CONTROL_DECK_DATE_INDEX - 1
        if control_step < 0:
            continue
        liquid, injection, oil = totals.get(control_step, (0.0, 0.0, 0.0))
        totals[control_step] = (
            liquid + state.liquid_rate,
            injection + state.injection_rate,
            oil + state.oil_rate,
        )
    found: list[Violation] = []
    for control_step in sorted(totals):
        liquid, injection, oil = totals[control_step]
        year = year_of_step(schedule, control_step)
        liquid_limit = constraints.liquid_limits.get(year)
        if liquid_limit is not None and liquid > liquid_limit:
            found.append(
                Violation(
                    kind=ViolationKind.LIQUID_LIMIT_EXCEEDED,
                    control_step=control_step,
                    well=None,
                    value=liquid,
                    detail=(
                        f"суммарная добыча жидкости {liquid} м³/сут выше лимита "
                        f"{liquid_limit} м³/сут на {year} год"
                    ),
                )
            )
        injection_limit = constraints.injection_limits.get(year)
        if injection_limit is not None and injection > injection_limit:
            found.append(
                Violation(
                    kind=ViolationKind.INJECTION_LIMIT_EXCEEDED,
                    control_step=control_step,
                    well=None,
                    value=injection,
                    detail=(
                        f"суммарная закачка {injection} м³/сут выше лимита "
                        f"{injection_limit} м³/сут на {year} год"
                    ),
                )
            )
        floor = constraints.production_floors.get(year)
        if floor is not None and oil < floor:
            found.append(
                Violation(
                    kind=ViolationKind.PRODUCTION_FLOOR_MISSED,
                    control_step=control_step,
                    well=None,
                    value=oil,
                    detail=(
                        f"суммарная добыча нефти {oil} т/сут ниже нижней границы "
                        f"{floor} т/сут на {year} год"
                    ),
                )
            )
        oil_limit = constraints.oil_limits.get(year)
        if oil_limit is not None and oil > oil_limit:
            found.append(
                Violation(
                    kind=ViolationKind.OIL_LIMIT_EXCEEDED,
                    control_step=control_step,
                    well=None,
                    value=oil,
                    detail=(
                        f"суммарная добыча нефти {oil} т/сут выше потолка "
                        f"{oil_limit} т/сут на {year} год"
                    ),
                )
            )
    return tuple(found), _rate_limit_checks(constraints, found)


def _rate_limit_checks(
    constraints: Constraints, found: Sequence[Violation]
) -> tuple[ConstraintCheck, ...]:
    sources: tuple[tuple[str, Mapping[int, float], str], ...] = (
        (
            CONSTRAINT_LIQUID_LIMITS,
            constraints.liquid_limits,
            "верхний предел суммарной добычи жидкости по годам",
        ),
        (
            CONSTRAINT_INJECTION_LIMITS,
            constraints.injection_limits,
            "верхний предел суммарной закачки по годам",
        ),
        (
            CONSTRAINT_PRODUCTION_FLOORS,
            constraints.production_floors,
            "нижняя граница суммарной добычи нефти по годам",
        ),
        (
            CONSTRAINT_OIL_LIMITS,
            constraints.oil_limits,
            "верхний предел суммарной добычи нефти по годам",
        ),
    )
    records: list[ConstraintCheck] = []
    for name, limits, meaning in sources:
        if not limits:
            records.append(
                _not_set(name, f"{name} в кейсе не заданы: {meaning} не проверялся")
            )
            continue
        years = ", ".join(str(year) for year in sorted(limits))
        records.append(
            _checked(
                name,
                found,
                f"{meaning} задан на годы {years} и сверен пошагово",
                blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
            )
        )
    return tuple(records)


def _check_watercut_limits(
    schedule: Schedule,
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints,
    oil_density_t_per_m3: float | None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    if not constraints.watercut_limits:
        return (), (
            _not_set(
                CONSTRAINT_WATERCUT_LIMITS,
                "watercut_limits в кейсе не заданы: обводнённость не проверялась",
            ),
        )
    if oil_density_t_per_m3 is None:
        raise ValueError(
            "watercut_limits заданы, но плотность нефти не передана: "
            "обводнённость производна и без ρ не определена"
        )
    totals: dict[int, tuple[float, float]] = {}
    for item in interval_responses:
        if is_excluded_by_negative_rule(item):
            continue
        oil, liquid = totals.get(item.control_step, (0.0, 0.0))
        totals[item.control_step] = (
            oil + item.oil_mass_delta,
            liquid + item.liquid_volume_delta,
        )
    found: list[Violation] = []
    for control_step in sorted(totals):
        oil, liquid = totals[control_step]
        if liquid <= 0.0:
            continue
        year = year_of_step(schedule, control_step)
        limit = constraints.watercut_limits.get(year)
        if limit is None:
            continue
        value = 1.0 - (oil / oil_density_t_per_m3) / liquid
        if value > limit:
            found.append(
                Violation(
                    kind=ViolationKind.WATERCUT_LIMIT_EXCEEDED,
                    control_step=control_step,
                    well=None,
                    value=value,
                    detail=(
                        f"обводнённость {value:.4f} выше предела {limit} "
                        f"на {year} год"
                    ),
                )
            )
    years = ", ".join(str(year) for year in sorted(constraints.watercut_limits))
    return tuple(found), (
        _checked(
            CONSTRAINT_WATERCUT_LIMITS,
            found,
            (
                f"предел обводнённости задан на годы {years} и сверен "
                f"на {len(totals)} шагах при плотности нефти "
                f"{oil_density_t_per_m3} т/м³"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


def _check_outages(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    constraints: Constraints,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    if not constraints.well_outages:
        return (), (
            _not_set(
                CONSTRAINT_WELL_OUTAGES,
                (
                    "well_outages в кейсе не заданы: работа скважин внутри "
                    "окон простоя не проверялась"
                ),
            ),
        )
    indexed = _states_by_step(states)
    found: list[Violation] = []
    for outage in constraints.well_outages:
        for control_step in range(
            outage.control_step_from, outage.control_step_to + 1
        ):
            state = indexed.get((control_step, outage.well))
            if state is None:
                continue
            flow = max(state.liquid_rate, state.injection_rate)
            if flow > 0.0:
                found.append(
                    Violation(
                        kind=ViolationKind.OUTAGE_WELL_PRODUCED,
                        control_step=control_step,
                        well=outage.well,
                        value=flow,
                        detail=(
                            f"скважина работает внутри окна простоя "
                            f"{outage.control_step_from}…{outage.control_step_to}"
                        ),
                    )
                )
    return tuple(found), (
        _checked(
            CONSTRAINT_WELL_OUTAGES,
            found,
            (
                f"окон простоя {len(constraints.well_outages)}: отклик сверен "
                "на нулевой дебит и нулевую закачку внутри каждого окна"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


def validate_dynamic(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints | None = None,
    oil_density_t_per_m3: float | None = None,
    report_undershoot: bool = True,
    field_series: FieldSeries | None = None,
    groups: Groups | None = None,
) -> DynamicReport:
    violations: list[Violation] = []
    undershoot, ratios = check_target_ratio(schedule, states)
    if report_undershoot:
        violations.extend(undershoot)
    violations.extend(check_control_modes(schedule, states))
    bhp_violations = check_bhp_limits(schedule, states, constraints)
    violations.extend(bhp_violations)
    violations.extend(check_role_consistency(schedule, states))
    violations.extend(check_intent_versus_fact(schedule, states))
    violations.extend(check_response_axes(schedule, states, interval_responses))
    violations.extend(check_interval_signs(interval_responses))
    constraint_violations, dynamic_checks = check_dynamic_constraints(
        schedule,
        states,
        interval_responses,
        constraints,
        oil_density_t_per_m3,
        field_series,
        groups,
    )
    violations.extend(constraint_violations)
    _, static_outage_check = check_constraints(
        candidates(schedule.control_events), constraints
    )
    checks = verified_constraint_checks(
        dynamic_checks
        + (static_outage_check, bhp_constraint_check(constraints, bhp_violations))
    )
    violations.sort(
        key=lambda item: (
            -1 if item.control_step is None else item.control_step,
            _well_sort_key(item.well) if item.well is not None else (2, 0, ""),
            item.kind.value,
        )
    )
    wells = {state.well for state in states}
    steps = {item.control_step for item in interval_responses}
    return DynamicReport(
        report=ValidationReport(
            violations=tuple(violations),
            n_control_events=len(schedule.control_events),
            n_fixed_events=len(schedule.fixed_deck_events),
            n_intervals=schedule.meta.n_intervals,
        ),
        ratios=ratios,
        n_states=len(states),
        n_intervals_seen=len(steps),
        n_wells=len(wells),
        blocking_kinds=ordered_violation_kinds(
            blocking_dynamic_violation_kinds(constraints)
        ),
        constraint_checks=checks,
    )
