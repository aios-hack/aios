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
from backend.core.contracts import (
    CompensationPolicy,
    Constraints,
    Groups,
    IntervalResponse,
    Schedule,
    compensation_policy,
)
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
                f"шаг {control_step}, {where}: отбор жидкости за шаг равен "
                f"{withdrawal:.6f} м³, компенсация C(k) = закачка / отбор "
                f"не определена и в коридор {minimum}…{maximum} "
                f"не проверялась; закачано {injection:.3f} м³; "
                f"условия расчёта: {conditions}; границы: {source}"
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
            f"{withdrawal:.3f} м³; условия расчёта: {conditions}; "
            f"границы: {source}"
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
    conditions: str,
    notice: str,
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
            conditions,
        )
        if violation is not None:
            found.append(violation)
    return tuple(found), _checked(
        CONSTRAINT_COMPENSATION,
        found,
        (
            f"коридор компенсации {minimum}…{maximum}, режим "
            f"{policy.enforcement}: C(k) = закачка / отбор проверена по полю "
            f"на {len(totals)} шагах в {conditions}{notice}"
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
                f"участок {group_id}",
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
            f"infrastructure.{COMPENSATION_SCOPE} = {policy.scope!r}: коридор "
            f"{minimum}…{maximum} проверен по участкам в {conditions}, нарезка "
            f"{groups.group_hash} из {len(groups.groups)} участков, "
            f"{len(totals)} пар шаг-участок{notice}"
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
            "коридор компенсации объявлен включённым, но границы не заданы: "
            "C(k) не с чем сравнивать"
        )
    source = (
        f"infrastructure.{COMPENSATION_MIN}/{COMPENSATION_MAX}, "
        f"режим {policy.enforcement}, {limit_origin(constraints, COMPENSATION_MIN)}"
    )
    if reservoir_factors is None:
        conditions = COMPENSATION_SURFACE_CONDITIONS
        notice = f"; {COMPENSATION_SURFACE_NOTICE}"
        field_totals = _compensation_totals(interval_responses)
    else:
        if oil_density_t_per_m3 is None:
            raise ValueError(
                "пересчёт компенсации в пластовые условия запрошен парой "
                "(B_o, B_w), но плотность нефти не передана: объём нефти в "
                "отборе по массе не восстановить, а подставить её за "
                "организаторов нельзя"
            )
        conditions = COMPENSATION_RESERVOIR_CONDITIONS
        notice = (
            f" по B_o/B_w на {len(reservoir_factors)} шагах при плотности "
            f"нефти {oil_density_t_per_m3} т/м³"
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
