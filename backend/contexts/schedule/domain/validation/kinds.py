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
            f"ограничение {constraint!r} не объявлено в отчёте о проверках: "
            "виды нарушений для него неизвестны"
        )
    return _CONSTRAINT_KINDS[constraint]


__all__ = [
    "constraint_kinds",
]
