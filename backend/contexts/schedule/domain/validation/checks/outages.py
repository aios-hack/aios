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
from backend.core.contracts import (
    Constraints,
    Schedule,
    StateAtDate,
)
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
                    "well_outages в кейсе не заданы: работа скважин внутри "
                    "окон простоя не проверялась"
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
                            f"скважина работает внутри окна простоя "
                            f"{outage.control_step_from}…{outage.control_step_to}"
                        ),
                    )
                )
    return tuple(found), (
        _checked(
            CONSTRAINT_WELL_OUTAGES,
            found,
            (
                f"окон простоя {len(constraints.well_outages)}: отклик сверен "
                "на нулевой дебит и нулевую закачку внутри каждого окна"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )
