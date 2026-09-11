from __future__ import annotations

from backend.contexts.schedule.domain.validation.kinds import (
    constraint_kinds,
)

from backend.contexts.schedule.domain.validation.outcomes import (
    _checked,
    _not_set,
)

from backend.contexts.schedule.domain.validation.constants import (
    COMPENSATION_FIELD_SCOPES,
    COMPENSATION_GROUP_SCOPES,
    COMPENSATION_RESERVOIR_CONDITIONS,
    COMPENSATION_SURFACE_CONDITIONS,
    COMPENSATION_SURFACE_NOTICE,
    CONSTRAINT_FIELD_COVERAGE,
    DYNAMIC_CONSTRAINT_NAMES,
    FIRST_CONTROL_DECK_DATE_INDEX,
    FIRST_CONTROL_LEVEL_DECK_DATE_INDEX,
    PHYSICS_CONSTRAINT_NAMES,
    PROVENANCE_FIELDS,
    _CONSTRAINT_KINDS,
)

from backend.contexts.schedule.domain.validation.checks.interval_signs import (
    check_interval_signs,
)

from backend.contexts.schedule.domain.validation.checks.response_axes import (
    check_response_axes,
)

from backend.contexts.schedule.domain.validation.checks.intent_versus_fact import (
    check_intent_versus_fact,
)

from backend.contexts.schedule.domain.validation.checks.role_consistency import (
    check_role_consistency,
)

from backend.contexts.schedule.domain.validation.checks.control_modes import (
    check_control_modes,
)

from backend.contexts.schedule.domain.validation.checks.bhp_limits import (
    bhp_constraint_check,
    check_bhp_limits,
)

from backend.contexts.schedule.domain.validation.checks.target_ratio import (
    check_target_ratio,
)

from backend.contexts.schedule.domain.validation.checks.outages import (
    _check_outages,
)

from backend.contexts.schedule.domain.validation.checks.watercut import (
    _check_watercut_limits,
)

from backend.contexts.schedule.domain.validation.checks.water_supply import (
    _check_water_supply,
    _days_in_step,
)

from backend.contexts.schedule.domain.validation.checks.rate_limits import (
    _check_rate_limits,
    _rate_limit_checks,
)

from backend.contexts.schedule.domain.validation.checks.material_balance import (
    _relative_error,
    check_material_balance,
)

from backend.contexts.schedule.domain.validation.checks.pressure import (
    _pressure_source,
    _region_pressure_source,
    check_field_pressure,
    check_region_pressure,
)

from backend.contexts.schedule.domain.validation.checks.compensation_totals import (
    _compensation_group_totals,
    _compensation_reservoir_totals,
    _compensation_totals,
    _group_membership,
    _reservoir_factors_at,
    reservoir_step_totals,
)
from backend.contexts.schedule.domain.validation.checks.compensation import (
    _check_compensation,
    _compensation_disabled_checks,
    _compensation_field_check,
    _compensation_groups_check,
    _compensation_violation,
)

from backend.contexts.schedule.domain.validation.coverage import (
    _absent_constraint_checks,
    constraint_fields_to_cover,
    verified_constraint_checks,
)

from backend.contexts.schedule.domain.validation.interpreter import (
    _Target,
    _apply_event,
    _commissioning_roles,
    _commissioning_steps,
    _initial_target,
    _states_by_step,
    _target_at,
    _target_timeline,
    control_step_of_level,
    control_step_pressures,
    level_deck_date_index,
    year_of_step,
)

from backend.contexts.schedule.domain.validation.report import (
    ACHIEVEMENT_THRESHOLD,
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
    DynamicReport,
    DynamicValidationError,
    FieldSeries,
    RegionSeries,
    TargetRatio,
    blocking_dynamic_violation_kinds,
    blocking_kinds_for_compensation,
    ordered_violation_kinds,
)

from backend.shared.errors import (
    ValidationError,
)

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
from backend.contexts.constraints.domain.constraints import (
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
    REGION_PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    WATER_REINJECTION_FRACTION,
    WATER_REINJECTION_LAG_STEPS,
    WATER_SUPPLY_UNLIMITED,
    FieldPressureLimits,
    RegionPressureLimits,
    bhp_limits,
    field_pressure_limits,
    limit_origin,
    region_pressure_limits,
)
from backend.contexts.reservoir.domain.response import N_DECK_DATES

from backend.contexts.schedule.domain.validate import (
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
    CONSTRAINT_REGION_PRESSURE,
    CONSTRAINT_MATERIAL_BALANCE,
    ConstraintCheck,
    ValidationReport,
    Violation,
    ViolationKind,
    _well_sort_key,
    candidates,
    check_constraints,
)
from backend.shared.numeric import relative_error


PRODUCER_MIN_BHP_BAR: float = DEFAULT_BHP_PRODUCER_MIN_BAR
INJECTOR_MAX_BHP_BAR: float = DEFAULT_BHP_INJECTOR_MAX_BAR


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
        ViolationKind.REGION_PRESSURE_BELOW_FLOOR,
        ViolationKind.REGION_PRESSURE_ABOVE_CEILING,
        ViolationKind.MATERIAL_BALANCE_BROKEN,
    }
)


def check_dynamic_constraints(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints | None,
    oil_density_t_per_m3: float | None = None,
    field_series: FieldSeries | None = None,
    groups: Groups | None = None,
    reservoir_factors: Sequence[tuple[float, float]] | None = None,
    region_series: RegionSeries | None = None,
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
        _check_compensation(
            schedule,
            interval_responses,
            constraints,
            groups,
            oil_density_t_per_m3,
            reservoir_factors,
        ),
        check_field_pressure(schedule, constraints, field_series),
        check_region_pressure(schedule, constraints, region_series),
        check_material_balance(field_series),
    ):
        found.extend(violations)
        checks.extend(records)
    return tuple(found), tuple(checks)


def validate_dynamic(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints | None = None,
    oil_density_t_per_m3: float | None = None,
    report_undershoot: bool = True,
    field_series: FieldSeries | None = None,
    groups: Groups | None = None,
    reservoir_factors: Sequence[tuple[float, float]] | None = None,
    region_series: RegionSeries | None = None,
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
        reservoir_factors,
        region_series,
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
            -1 if item.region is None else item.region,
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
