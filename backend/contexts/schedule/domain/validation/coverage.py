from __future__ import annotations

from backend.contexts.schedule.domain.validation.kinds import (
    constraint_kinds,
)

from backend.contexts.schedule.domain.validation.outcomes import (
    _not_set,
)

from backend.contexts.schedule.domain.validation.checks.material_balance import (
    check_material_balance,
)
from backend.contexts.schedule.domain.validation.constants import (
    CONSTRAINT_FIELD_COVERAGE,
    DYNAMIC_CONSTRAINT_NAMES,
    PHYSICS_CONSTRAINT_NAMES,
    PROVENANCE_FIELDS,
    _CONSTRAINT_KINDS,
)

from backend.contexts.schedule.domain.validation.report import (
    FieldSeries,
)
from collections.abc import (
    Sequence,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.constraints.domain.constraints import (
    BHP_INJECTOR_MAX_BAR,
    BHP_PRODUCER_MIN_BAR,
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    COMPENSATION_SCOPE,
    EXTERNAL_WATER_M3_PER_DAY,
    PRESSURE_CEILING_BAR,
    PRESSURE_FLOOR_BAR,
    REGION_PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    WATER_REINJECTION_FRACTION,
    WATER_REINJECTION_LAG_STEPS,
    WATER_SUPPLY_UNLIMITED,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_WELL_OUTAGES_STATIC,
    CONSTRAINT_MATERIAL_BALANCE,
    ConstraintCheck,
    ViolationKind,
)


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
        REGION_PRESSURE_FLOOR_BAR,
        REGION_PRESSURE_CEILING_BAR,
    )


def verified_constraint_checks(
    checks: Sequence[ConstraintCheck],
) -> tuple[ConstraintCheck, ...]:
    present = {item.constraint for item in checks}
    if len(present) != len(checks):
        raise ValueError(
            "the report of applied constraints contains duplicate entries: "
            "one constraint must yield exactly one status"
        )
    missing_physics = [
        name for name in PHYSICS_CONSTRAINT_NAMES if name not in present
    ]
    if missing_physics:
        raise ValueError(
            "the report of applied constraints contains no entries for the "
            f"physics checks: {', '.join(sorted(missing_physics))}; a check "
            "that does not depend on the case must still state its status"
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
            "the report of applied constraints is incomplete, case fields "
            f"left without an entry: {', '.join(sorted(uncovered))}; a field "
            "declared in Constraints must receive a check status, otherwise "
            "sound=true hides an unchecked constraint"
        )
    return tuple(sorted(checks, key=lambda item: item.constraint))


def _absent_constraint_checks(
    field_series: FieldSeries | None = None,
) -> tuple[ConstraintCheck, ...]:
    detail = (
        "the case constraints were not supplied: dynamic checks were not run"
    )
    names = tuple(
        name for name in DYNAMIC_CONSTRAINT_NAMES
        if name != CONSTRAINT_MATERIAL_BALANCE
    )
    _, balance_checks = check_material_balance(field_series)
    return tuple(_not_set(name, detail) for name in names) + balance_checks


__all__ = [
    "constraint_fields_to_cover",
    "constraint_kinds",
    "verified_constraint_checks",
]
