from __future__ import annotations

from backend.contexts.schedule.domain.validation.outcomes import (
    _checked,
    _not_set,
)
from backend.contexts.schedule.domain.validation.interpreter import (
    _states_by_step,
)
from backend.contexts.schedule.domain.validation.report import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
)
from collections.abc import (
    Sequence,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.reservoir.domain.response import StateAtDate
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_WELL_OUTAGES,
    ConstraintCheck,
    Violation,
    ViolationKind,
)


def _check_outages(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    constraints: Constraints,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    if not constraints.well_outages:
        return (), (
            _not_set(
                CONSTRAINT_WELL_OUTAGES,
                (
                    "well_outages are not set in the case: well operation "
                    "inside outage windows was not checked"
                ),
            ),
        )
    indexed = _states_by_step(states)
    found: list[Violation] = []
    for outage in constraints.well_outages:
        for control_step in range(
            outage.control_step_from, outage.control_step_to + 1
        ):
            state = indexed.get((control_step, outage.well))
            if state is None:
                continue
            flow = max(state.liquid_rate, state.injection_rate)
            if flow > 0.0:
                found.append(
                    Violation(
                        kind=ViolationKind.OUTAGE_WELL_PRODUCED,
                        control_step=control_step,
                        well=outage.well,
                        value=flow,
                        detail=(
                            f"the well operates inside the outage window "
                            f"{outage.control_step_from}..."
                            f"{outage.control_step_to}"
                        ),
                    )
                )
    return tuple(found), (
        _checked(
            CONSTRAINT_WELL_OUTAGES,
            found,
            (
                f"outage windows {len(constraints.well_outages)}: the "
                "response was checked for zero rate and zero injection "
                "inside each window"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )
