from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from contracts import (
    ActiveControlMode,
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    IntervalResponse,
    N_INTERVALS,
    OperatingStatus,
    Role,
    Schedule,
    StateAtDate,
    WellState,
    is_excluded_by_negative_rule,
)
from contracts.response import N_DECK_DATES

from .validate import ValidationReport, Violation, ViolationKind, _well_sort_key

PRODUCER_MIN_BHP_BAR: float = 50.0
INJECTOR_MAX_BHP_BAR: float = 300.0
ACHIEVEMENT_THRESHOLD: float = 0.999
FIRST_CONTROL_DECK_DATE_INDEX: int = N_DECK_DATES - N_INTERVALS - 1


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
        ViolationKind.WATERCUT_LIMIT_EXCEEDED,
        ViolationKind.OUTAGE_WELL_PRODUCED,
    }
)


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

    @property
    def ok(self) -> bool:
        return self.report.ok

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


def check_bhp_limits(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    producer_min_bar: float = PRODUCER_MIN_BHP_BAR,
    injector_max_bar: float = INJECTOR_MAX_BHP_BAR,
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
                            f"выше предела {injector_max_bar} бар"
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
                            f"ниже предела {producer_min_bar} бар"
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


def _year_of_step(schedule: Schedule, control_step: int) -> int:
    t0 = schedule.meta.t0
    month_index = t0.month - 1 + control_step
    return t0.year + month_index // 12


def check_dynamic_constraints(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints | None,
    oil_density_t_per_m3: float | None = None,
) -> tuple[Violation, ...]:
    if constraints is None:
        return ()
    found: list[Violation] = []
    found.extend(_check_rate_limits(schedule, states, constraints))
    found.extend(
        _check_watercut_limits(
            schedule, interval_responses, constraints, oil_density_t_per_m3
        )
    )
    found.extend(_check_outages(schedule, states, constraints))
    return tuple(found)


def _check_rate_limits(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    constraints: Constraints,
) -> tuple[Violation, ...]:
    if not (
        constraints.liquid_limits
        or constraints.injection_limits
        or constraints.production_floors
    ):
        return ()
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
        year = _year_of_step(schedule, control_step)
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
    return tuple(found)


def _check_watercut_limits(
    schedule: Schedule,
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints,
    oil_density_t_per_m3: float | None,
) -> tuple[Violation, ...]:
    if not constraints.watercut_limits:
        return ()
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
        year = _year_of_step(schedule, control_step)
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
    return tuple(found)


def _check_outages(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    constraints: Constraints,
) -> tuple[Violation, ...]:
    if not constraints.well_outages:
        return ()
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
    return tuple(found)


def validate_dynamic(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints | None = None,
    oil_density_t_per_m3: float | None = None,
    report_undershoot: bool = True,
) -> DynamicReport:
    violations: list[Violation] = []
    undershoot, ratios = check_target_ratio(schedule, states)
    if report_undershoot:
        violations.extend(undershoot)
    violations.extend(check_control_modes(schedule, states))
    violations.extend(check_bhp_limits(schedule, states))
    violations.extend(check_role_consistency(schedule, states))
    violations.extend(check_intent_versus_fact(schedule, states))
    violations.extend(check_response_axes(schedule, states, interval_responses))
    violations.extend(check_interval_signs(interval_responses))
    violations.extend(
        check_dynamic_constraints(
            schedule,
            states,
            interval_responses,
            constraints,
            oil_density_t_per_m3,
        )
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
    )
