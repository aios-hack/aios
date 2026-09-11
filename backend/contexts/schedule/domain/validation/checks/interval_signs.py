from __future__ import annotations

from collections.abc import (
    Sequence,
)
from backend.contexts.reservoir.domain.response import (
    IntervalResponse,
    is_excluded_by_negative_rule,
)
from backend.contexts.schedule.domain.validate import (
    Violation,
    ViolationKind,
    _well_sort_key,
)


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
                    "negative monthly increment: the cumulative quantities "
                    "of the simulator must be monotonic"
                ),
            )
        )
    return tuple(found)


__all__ = [
    "check_interval_signs",
]
