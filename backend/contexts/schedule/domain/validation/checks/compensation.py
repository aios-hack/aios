from __future__ import annotations

from backend.contexts.schedule.domain.validation.checks.compensation_totals import (
    _compensation_group_totals,
    _compensation_reservoir_totals,
    _compensation_totals,
    reservoir_step_totals,
)

from backend.contexts.schedule.domain.validation.constants import (
    COMPENSATION_FIELD_SCOPES,
    COMPENSATION_GROUP_SCOPES,
    COMPENSATION_RESERVOIR_CONDITIONS,
    COMPENSATION_SURFACE_CONDITIONS,
    COMPENSATION_SURFACE_NOTICE,
)

from backend.contexts.schedule.domain.validation.coverage import (
    constraint_kinds,
)
from backend.contexts.schedule.domain.validation.outcomes import (
    _checked,
    _not_set,
)
from backend.contexts.schedule.domain.validation.report import (
    blocking_kinds_for_compensation,
)
from collections.abc import (
    Mapping,
    Sequence,
)
from backend.contexts.constraints.domain.constraints import (
    CompensationPolicy,
    Constraints,
    compensation_policy,
)
from backend.contexts.connectivity.domain.connectivity import Groups
from backend.contexts.reservoir.domain.response import IntervalResponse
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.constraints.domain.constraints import (
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    COMPENSATION_SCOPE,
    limit_origin,
)
from backend.contexts.schedule.domain.validate import (
    STATUS_CHECKED,
    CONSTRAINT_COMPENSATION,
    CONSTRAINT_COMPENSATION_SCOPE,
    ConstraintCheck,
    Violation,
    ViolationKind,
)


def _compensation_violation(
    control_step: int,
    withdrawal: float,
    injection: float,
    minimum: float,
    maximum: float,
    source: str,
    where: str,
    conditions: str = COMPENSATION_SURFACE_CONDITIONS,
) -> Violation | None:
    if withdrawal <= 0.0:
        return Violation(
            kind=ViolationKind.COMPENSATION_UNDEFINED,
            control_step=control_step,
            well=None,
            value=injection,
            detail=(
                f"step {control_step}, {where}: liquid withdrawal over the "
                f"step equals {withdrawal:.6f} m3, compensation "
                f"C(k) = injection / withdrawal is undefined and was not "
                f"checked against the corridor {minimum}...{maximum}; "
                f"injected {injection:.3f} m3; calculation conditions: "
                f"{conditions}; bounds: {source}"
            ),
        )
    value = injection / withdrawal
    if minimum <= value <= maximum:
        return None
    side = "below the lower" if value < minimum else "above the upper"
    return Violation(
        kind=ViolationKind.COMPENSATION_OUT_OF_CORRIDOR,
        control_step=control_step,
        well=None,
        value=value,
        detail=(
            f"step {control_step}, {where}: compensation C(k) = {value:.4f} "
            f"is {side} bound of the corridor {minimum}...{maximum}; "
            f"injected {injection:.3f} m3 against liquid withdrawal "
            f"{withdrawal:.3f} m3; calculation conditions: {conditions}; "
            f"bounds: {source}"
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
                "are not set: the compensation corridor C(k) was not checked"
            ),
            enforcement=policy.enforcement,
        ),
        _not_set(
            CONSTRAINT_COMPENSATION_SCOPE,
            (
                f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}, "
                "but the corridor is disabled: there is nothing to apply the "
                "check scope to"
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
    conditions: str,
    notice: str,
) -> tuple[tuple[Violation, ...], ConstraintCheck]:
    if policy.scope not in COMPENSATION_FIELD_SCOPES:
        return (), _not_set(
            CONSTRAINT_COMPENSATION,
            (
                f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}: "
                "the case requires the corridor only per group, the "
                "whole-field breakdown was not requested"
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
            "the whole field",
            conditions,
        )
        if violation is not None:
            found.append(violation)
    return tuple(found), _checked(
        CONSTRAINT_COMPENSATION,
        found,
        (
            f"compensation corridor {minimum}...{maximum}, mode "
            f"{policy.enforcement}: C(k) = injection / withdrawal checked "
            f"over the field on {len(totals)} steps under {conditions}"
            f"{notice}"
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
    conditions: str,
    notice: str,
    reservoir_factors: Sequence[tuple[float, float]] | None = None,
    oil_density_t_per_m3: float | None = None,
) -> tuple[tuple[Violation, ...], ConstraintCheck]:
    if policy.scope not in COMPENSATION_GROUP_SCOPES:
        return (), _checked(
            CONSTRAINT_COMPENSATION_SCOPE,
            (),
            (
                f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}: "
                "the case requires the corridor only over the whole field, "
                "the per-group breakdown was not requested"
            ),
            blocking_kinds=frozenset(),
            enforcement=policy.enforcement,
        )
    if groups is None:
        raise ValueError(
            f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r} "
            "requires the well stock to be split into groups, but Groups "
            "were not supplied to the validator: the per-group corridor C(k) "
            "is declared by the case and must be computed. Skipping it would "
            "mean reporting sound=true for a constraint nobody checked"
        )
    totals = _compensation_group_totals(
        interval_responses, groups, reservoir_factors, oil_density_t_per_m3
    )
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
                f"group {group_id}",
                conditions,
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
            f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}: the "
            f"corridor {minimum}...{maximum} was checked per group under "
            f"{conditions}, split {groups.group_hash} of "
            f"{len(groups.groups)} groups, {len(totals)} step-group pairs"
            f"{notice}"
        ),
    )


def _check_compensation(
    schedule: Schedule,
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints,
    groups: Groups | None = None,
    oil_density_t_per_m3: float | None = None,
    reservoir_factors: Sequence[tuple[float, float]] | None = None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    policy = compensation_policy(constraints)
    if not policy.enabled:
        return (), _compensation_disabled_checks(policy)
    minimum = policy.minimum
    maximum = policy.maximum
    if minimum is None or maximum is None:
        raise ValueError(
            "the compensation corridor is declared enabled, but the bounds "
            "are not set: there is nothing to compare C(k) against"
        )
    source = (
        f"infrastructure.{COMPENSATION_MIN}/{COMPENSATION_MAX}, "
        f"mode {policy.enforcement}, "
        f"{limit_origin(constraints, COMPENSATION_MIN)}"
    )
    if reservoir_factors is None:
        conditions = COMPENSATION_SURFACE_CONDITIONS
        notice = f"; {COMPENSATION_SURFACE_NOTICE}"
        field_totals = _compensation_totals(interval_responses)
    else:
        if oil_density_t_per_m3 is None:
            raise ValueError(
                "conversion of compensation to reservoir conditions was "
                "requested by the (B_o, B_w) pair, but oil density was not "
                "supplied: the oil volume in the withdrawal cannot be "
                "recovered from mass, and it must not be substituted on "
                "behalf of the organizers"
            )
        conditions = COMPENSATION_RESERVOIR_CONDITIONS
        notice = (
            f" by B_o/B_w on {len(reservoir_factors)} steps at oil density "
            f"{oil_density_t_per_m3} t/m3"
        )
        field_totals = _compensation_reservoir_totals(
            interval_responses, reservoir_factors, oil_density_t_per_m3
        )
    field_found, field_check = _compensation_field_check(
        schedule,
        field_totals,
        policy,
        minimum,
        maximum,
        source,
        conditions,
        notice,
    )
    group_found, group_check = _compensation_groups_check(
        schedule,
        interval_responses,
        groups,
        policy,
        minimum,
        maximum,
        source,
        conditions,
        notice,
        reservoir_factors,
        oil_density_t_per_m3,
    )
    return field_found + group_found, (field_check, group_check)


__all__ = [
    "reservoir_step_totals",
]
