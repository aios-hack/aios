from __future__ import annotations

from collections.abc import Mapping, Sequence

from backend.contexts.schedule.domain.schedule import (
    Availability,
    EventKind,
    FixedDeckEvent,
    Role,
    WellState,
)
from backend.contexts.schedule.domain.validate.events import (
    CandidateEvent,
    _COMMISSIONING_OPERATORS,
    _event_sort_key,
)
from backend.contexts.schedule.domain.validate.vocabulary import (
    Violation,
    ViolationKind,
)


def commissioning_steps(
    fixed_deck_events: Sequence[FixedDeckEvent],
) -> dict[str, int]:
    steps: dict[str, int] = {}
    for event in fixed_deck_events:
        if event.operator not in _COMMISSIONING_OPERATORS:
            continue
        current = steps.get(event.well)
        if current is None or event.control_step < current:
            steps[event.well] = event.control_step
    return steps


def commissioning_roles(
    fixed_deck_events: Sequence[FixedDeckEvent],
) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for event in sorted(fixed_deck_events, key=lambda item: item.control_step):
        if event.operator == "WCONPROD":
            roles.setdefault(event.well, Role.PROD)
        elif event.operator == "WCONINJE":
            roles.setdefault(event.well, Role.INJ)
    return roles


def check_roles_and_conversions(
    events: Sequence[CandidateEvent],
    initial_state: Mapping[str, WellState],
    fixed_deck_events: Sequence[FixedDeckEvent] = (),
) -> tuple[Violation, ...]:
    found: list[Violation] = []
    roles = {well: state.role for well, state in initial_state.items()}
    availability = {
        well: state.availability for well, state in initial_state.items()
    }
    commissioned_at = commissioning_steps(fixed_deck_events)
    commissioned_roles = commissioning_roles(fixed_deck_events)
    conversion_steps = {
        (event.control_step, event.well)
        for event in events
        if event.kind is EventKind.CONVERT_INJ
    }
    converted: dict[str, int] = {}
    for event in sorted(events, key=_event_sort_key):
        well = event.well
        commissioning_step = commissioned_at.get(well)
        if (
            commissioning_step is not None
            and availability.get(well) is Availability.NOT_COMMISSIONED
            and event.control_step >= commissioning_step
        ):
            availability[well] = Availability.AVAILABLE
            roles[well] = commissioned_roles.get(well, roles.get(well, Role.NONE))
        if well not in initial_state:
            found.append(
                Violation(
                    kind=ViolationKind.WELL_NOT_ON_AXIS,
                    control_step=event.control_step,
                    well=well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name}: the well is not in "
                        f"initial_state, there is nobody to address the event "
                        f"to"
                    ),
                )
            )
            continue
        if availability[well] is Availability.NOT_COMMISSIONED:
            found.append(
                Violation(
                    kind=ViolationKind.WELL_NOT_COMMISSIONED,
                    control_step=event.control_step,
                    well=well,
                    value=event.value,
                    detail=(
                        f"{event.kind.name} is addressed to a well in the "
                        f"NOT_COMMISSIONED state: commissioning dates are not "
                        f"our lever"
                    ),
                )
            )
            continue
        role = roles[well]
        closes_producer_on_conversion = (
            event.kind is EventKind.SET_LRAT
            and event.value == 0.0
            and (event.control_step, well) in conversion_steps
        )
        if closes_producer_on_conversion:
            continue
        if event.kind is EventKind.SET_LRAT and role is Role.INJ:
            found.append(
                Violation(
                    kind=ViolationKind.SET_LRAT_ON_INJECTOR,
                    control_step=event.control_step,
                    well=well,
                    value=event.value,
                    detail="SET_LRAT is addressed to a well in the INJ role",
                )
            )
        elif event.kind is EventKind.SET_RATE and role is Role.PROD:
            found.append(
                Violation(
                    kind=ViolationKind.SET_RATE_ON_PRODUCER,
                    control_step=event.control_step,
                    well=well,
                    value=event.value,
                    detail="SET_RATE is addressed to a well in the PROD role",
                )
            )
        elif event.kind is EventKind.CONVERT_INJ:
            if role is Role.INJ and well not in converted:
                found.append(
                    Violation(
                        kind=ViolationKind.CONVERT_INJ_ON_INJECTOR,
                        control_step=event.control_step,
                        well=well,
                        value=None,
                        detail=(
                            "CONVERT_INJ is addressed to a well already in "
                            "the INJ role"
                        ),
                    )
                )
            elif well in converted:
                found.append(
                    Violation(
                        kind=ViolationKind.CONVERT_INJ_REPEATED,
                        control_step=event.control_step,
                        well=well,
                        value=None,
                        detail=(
                            f"repeated CONVERT_INJ: the first one was on "
                            f"step {converted[well]}"
                        ),
                    )
                )
            else:
                converted[well] = event.control_step
                roles[well] = Role.INJ
    return tuple(found)
