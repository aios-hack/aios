from __future__ import annotations

from backend.contexts.schedule.domain.validation.kinds import (
    constraint_kinds,
)

from collections.abc import (
    Sequence,
)
from backend.contexts.schedule.domain.validate import (
    STATUS_CHECKED,
    STATUS_NOT_SET,
    ConstraintCheck,
    Violation,
    ViolationKind,
)


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
