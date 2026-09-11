from __future__ import annotations

from backend.contexts.schedule.domain.validation.constants import (
    CONSTRAINT_FIELD_COVERAGE,
    DYNAMIC_CONSTRAINT_NAMES,
    PHYSICS_CONSTRAINT_NAMES,
    PROVENANCE_FIELDS,
    _CONSTRAINT_KINDS,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_WELL_OUTAGES_STATIC,
    CONSTRAINT_MATERIAL_BALANCE,
    ConstraintCheck,
    ViolationKind,
)


def constraint_kinds(constraint: str) -> tuple[ViolationKind, ...]:
    if constraint == CONSTRAINT_WELL_OUTAGES_STATIC:
        return (ViolationKind.WELL_OUTAGE_VIOLATED,)
    if constraint not in _CONSTRAINT_KINDS:
        raise KeyError(
            f"constraint {constraint!r} is not declared in the check "
            "report: the violation kinds for it are unknown"
        )
    return _CONSTRAINT_KINDS[constraint]


__all__ = [
    "constraint_kinds",
]
