from __future__ import annotations

from backend.contexts.schedule.domain.validation.constants import (
    FIRST_CONTROL_DECK_DATE_INDEX,
)

from backend.contexts.schedule.domain.validation.outcomes import (
    _checked,
    _not_set,
)
from backend.contexts.schedule.domain.validation.interpreter import (
    year_of_step,
)
from backend.contexts.schedule.domain.validation.report import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
)
from collections.abc import (
    Mapping,
    Sequence,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.reservoir.domain.response import StateAtDate
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_INJECTION_LIMITS,
    CONSTRAINT_LIQUID_LIMITS,
    CONSTRAINT_OIL_LIMITS,
    CONSTRAINT_PRODUCTION_FLOORS,
    ConstraintCheck,
    Violation,
    ViolationKind,
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
                        f"total liquid production {liquid} m3/day is above "
                        f"the limit {liquid_limit} m3/day for year {year}"
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
                        f"total injection {injection} m3/day is above the "
                        f"limit {injection_limit} m3/day for year {year}"
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
                        f"total oil production {oil} t/day is below the "
                        f"lower bound {floor} t/day for year {year}"
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
                        f"total oil production {oil} t/day is above the "
                        f"ceiling {oil_limit} t/day for year {year}"
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
            "the upper limit of total liquid production by year",
        ),
        (
            CONSTRAINT_INJECTION_LIMITS,
            constraints.injection_limits,
            "the upper limit of total injection by year",
        ),
        (
            CONSTRAINT_PRODUCTION_FLOORS,
            constraints.production_floors,
            "the lower bound of total oil production by year",
        ),
        (
            CONSTRAINT_OIL_LIMITS,
            constraints.oil_limits,
            "the upper limit of total oil production by year",
        ),
    )
    records: list[ConstraintCheck] = []
    for name, limits, meaning in sources:
        if not limits:
            records.append(
                _not_set(
                    name,
                    f"{name} are not set in the case: {meaning} was not "
                    f"checked",
                )
            )
            continue
        years = ", ".join(str(year) for year in sorted(limits))
        records.append(
            _checked(
                name,
                found,
                f"{meaning} is set for years {years} and checked step by "
                f"step",
                blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
            )
        )
    return tuple(records)
