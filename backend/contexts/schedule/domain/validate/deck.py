from __future__ import annotations

from collections.abc import Sequence

from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.canonical import (
    canonical_part_hash,
    find_control_conflicts,
)
from backend.contexts.schedule.domain.schedule import (
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    MAX_LRAT_M3_PER_DAY,
    N_INTERVALS,
)
from backend.contexts.schedule.domain.validate.events import (
    CandidateEvent,
    _event_sort_key,
)
from backend.contexts.schedule.domain.validate.vocabulary import (
    CONSTRAINT_WELL_OUTAGES_STATIC,
    ConstraintCheck,
    STATUS_CHECKED,
    STATUS_NOT_SET,
    Violation,
    ViolationKind,
)


def _is_constructible(event: CandidateEvent) -> bool:
    if not (0 <= event.control_step < N_INTERVALS):
        return False
    needs_value = event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE)
    if needs_value != (event.value is not None):
        return False
    if event.value is not None and event.value < 0:
        return False
    if event.kind is EventKind.SET_LRAT and event.value is not None:
        if event.value > MAX_LRAT_M3_PER_DAY:
            return False
    return True


def check_conflicts(events: Sequence[CandidateEvent]) -> tuple[Violation, ...]:
    control_events = tuple(
        ControlEvent(
            control_step=event.control_step,
            well=event.well,
            kind=event.kind,
            value=event.value,
        )
        for event in events
        if _is_constructible(event)
    )
    found: list[Violation] = []
    for step, well, kind, values in find_control_conflicts(control_events):
        found.append(
            Violation(
                kind=ViolationKind.CONFLICTING_EVENTS,
                control_step=step,
                well=well,
                value=None,
                detail=(
                    f"several mismatching {kind.name} on one step: values "
                    f"{values}"
                ),
            )
        )
    return tuple(found)


def fixed_layer_hash(events: Sequence[FixedDeckEvent]) -> str:
    return canonical_part_hash(list(events))


def check_fixed_layer(
    events: Sequence[FixedDeckEvent], expected_hash: str | None
) -> tuple[Violation, ...]:
    if expected_hash is None:
        return ()
    actual = fixed_layer_hash(events)
    if actual == expected_hash:
        return ()
    return (
        Violation(
            kind=ViolationKind.FIXED_LAYER_CHANGED,
            control_step=None,
            well=None,
            value=None,
            detail=(
                f"the fixed layer of the deck was modified: hash {actual} "
                f"against the reference {expected_hash}"
            ),
        ),
    )


def check_constraints(
    events: Sequence[CandidateEvent], constraints: Constraints | None
) -> tuple[tuple[Violation, ...], ConstraintCheck]:
    kinds = (ViolationKind.WELL_OUTAGE_VIOLATED,)
    if constraints is None or not constraints.well_outages:
        return (), ConstraintCheck(
            constraint=CONSTRAINT_WELL_OUTAGES_STATIC,
            status=STATUS_NOT_SET,
            kinds=kinds,
            n_violations=None,
            blocking=True,
            enforcement=None,
            detail=(
                "well_outages are not set in the case: the static check of "
                "events inside outage windows was not run"
            ),
        )
    found: list[Violation] = []
    for outage in constraints.well_outages:
        for event in sorted(events, key=_event_sort_key):
            if event.well != outage.well:
                continue
            if not (outage.control_step_from <= event.control_step <= outage.control_step_to):
                continue
            if event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE) and event.value:
                found.append(
                    Violation(
                        kind=ViolationKind.WELL_OUTAGE_VIOLATED,
                        control_step=event.control_step,
                        well=event.well,
                        value=event.value,
                        detail=(
                            f"{event.kind.name} with a positive setpoint "
                            f"inside the outage window "
                            f"{outage.control_step_from}..."
                            f"{outage.control_step_to}"
                        ),
                    )
                )
            elif event.kind is EventKind.OPEN:
                found.append(
                    Violation(
                        kind=ViolationKind.WELL_OUTAGE_VIOLATED,
                        control_step=event.control_step,
                        well=event.well,
                        value=None,
                        detail=(
                            f"OPEN inside the outage window "
                            f"{outage.control_step_from}..."
                            f"{outage.control_step_to}"
                        ),
                    )
                )
    return tuple(found), ConstraintCheck(
        constraint=CONSTRAINT_WELL_OUTAGES_STATIC,
        status=STATUS_CHECKED,
        kinds=kinds,
        n_violations=len(found),
        blocking=True,
        enforcement=None,
        detail=(
            f"outage windows {len(constraints.well_outages)}: schedule "
            "events were checked for positive setpoints and OPEN inside a "
            "window"
        ),
    )
