from __future__ import annotations

from backend.contexts.schedule.domain.validation.outcomes import (
    _checked,
)
from backend.contexts.schedule.domain.validation.interpreter import (
    _states_by_step,
    _target_at,
    _target_timeline,
)
from backend.contexts.schedule.domain.validation.report import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
)
from collections.abc import (
    Sequence,
)
from backend.core.contracts import (
    ActiveControlMode,
    Constraints,
    Role,
    Schedule,
    StateAtDate,
)
from backend.contexts.constraints.domain.constraints import (
    BHP_INJECTOR_MAX_BAR,
    BHP_PRODUCER_MIN_BAR,
    bhp_limits,
    limit_origin,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_BHP_LIMITS,
    ConstraintCheck,
    Violation,
    ViolationKind,
    _well_sort_key,
)


def bhp_constraint_check(
    constraints: Constraints | None, found: Sequence[Violation]
) -> ConstraintCheck:
    case = constraints if constraints is not None else Constraints()
    limits = bhp_limits(case)
    return _checked(
        CONSTRAINT_BHP_LIMITS,
        found,
        (
            f"коридор забойного давления {limits.producer_min_bar}…"
            f"{limits.injector_max_bar} бар: нижний предел добывающих "
            f"infrastructure.{BHP_PRODUCER_MIN_BAR}, "
            f"{limit_origin(case, BHP_PRODUCER_MIN_BAR)}; верхний предел "
            f"нагнетательных infrastructure.{BHP_INJECTOR_MAX_BAR}, "
            f"{limit_origin(case, BHP_INJECTOR_MAX_BAR)}"
        ),
        blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
    )


def check_bhp_limits(
    schedule: Schedule,
    states: Sequence[StateAtDate],
    constraints: Constraints | None = None,
    producer_min_bar: float | None = None,
    injector_max_bar: float | None = None,
) -> tuple[Violation, ...]:
    case = constraints if constraints is not None else Constraints()
    limits = bhp_limits(case)
    if producer_min_bar is None:
        producer_min_bar = limits.producer_min_bar
    if injector_max_bar is None:
        injector_max_bar = limits.injector_max_bar
    producer_origin = limit_origin(case, BHP_PRODUCER_MIN_BAR)
    injector_origin = limit_origin(case, BHP_INJECTOR_MAX_BAR)
    timelines = _target_timeline(schedule)
    indexed = _states_by_step(states)
    found: list[Violation] = []
    for (control_step, well), state in sorted(
        indexed.items(), key=lambda item: (item[0][0], _well_sort_key(item[0][1]))
    ):
        timeline = timelines.get(well)
        if timeline is None:
            continue
        target = _target_at(timeline, control_step)
        if not target.commissioned:
            continue
        if state.active_control_mode in (
            ActiveControlMode.SHUT,
            ActiveControlMode.NOT_COMMISSIONED,
        ):
            continue
        if target.role is Role.INJ:
            if state.bhp > injector_max_bar:
                found.append(
                    Violation(
                        kind=ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
                        control_step=control_step,
                        well=well,
                        value=state.bhp,
                        detail=(
                            f"забойное давление нагнетательной {state.bhp} бар "
                            f"выше предела {injector_max_bar} бар; предел "
                            f"infrastructure.{BHP_INJECTOR_MAX_BAR}, "
                            f"{injector_origin}"
                        ),
                    )
                )
        elif target.role is Role.PROD:
            if state.liquid_rate <= 0.0:
                continue
            if state.bhp < producer_min_bar:
                found.append(
                    Violation(
                        kind=ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
                        control_step=control_step,
                        well=well,
                        value=state.bhp,
                        detail=(
                            f"забойное давление добывающей {state.bhp} бар "
                            f"ниже предела {producer_min_bar} бар; предел "
                            f"infrastructure.{BHP_PRODUCER_MIN_BAR}, "
                            f"{producer_origin}"
                        ),
                    )
                )
    return tuple(found)


__all__ = [
    "bhp_constraint_check",
    "check_bhp_limits",
]
