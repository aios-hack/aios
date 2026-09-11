from __future__ import annotations

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
    Sequence,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.reservoir.domain.response import (
    IntervalResponse,
    is_excluded_by_negative_rule,
)
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_WATERCUT_LIMITS,
    ConstraintCheck,
    Violation,
    ViolationKind,
)


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
                "watercut_limits are not set in the case: watercut was not "
                "checked",
            ),
        )
    if oil_density_t_per_m3 is None:
        raise ValueError(
            "watercut_limits are set, but oil density was not supplied: "
            "watercut is derived and undefined without rho"
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
                        f"watercut {value:.4f} is above the limit {limit} "
                        f"for year {year}"
                    ),
                )
            )
    years = ", ".join(str(year) for year in sorted(constraints.watercut_limits))
    return tuple(found), (
        _checked(
            CONSTRAINT_WATERCUT_LIMITS,
            found,
            (
                f"the watercut limit is set for years {years} and checked "
                f"on {len(totals)} steps at oil density "
                f"{oil_density_t_per_m3} t/m3"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )
