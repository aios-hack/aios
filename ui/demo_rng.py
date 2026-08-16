from __future__ import annotations

from contracts import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    WellState,
)

DEMO_PROVENANCE = "synthetic-demo"
DEMO_SEED = 20260815
DEMO_HASH_PREFIX = "demo"
NOT_COMMISSIONED_TAIL = 22
GROUP_COUNT = 6
DEMO_SCALE = 1.0e-3
_MULT = 6364136223846793005
_INC = 1442695040888963407
_MASK = (1 << 64) - 1
_INJECTOR_SHARE = 4


def demo_hash(tag: str) -> str:
    state = DEMO_SEED
    for ch in tag:
        state = (state * _MULT + ord(ch)) & _MASK
    return (DEMO_HASH_PREFIX + f"{state:016x}" * 4)[:64]


class Rng:
    def __init__(self, seed: int) -> None:
        self.state = seed & _MASK

    def unit(self) -> float:
        self.state = (self.state * _MULT + _INC) & _MASK
        return (self.state >> 11) / float(1 << 53)

    def between(self, low: float, high: float) -> float:
        return low + (high - low) * self.unit()


def roles_of(wells: tuple[str, ...]) -> dict[str, Role]:
    commissioned = wells[: len(wells) - NOT_COMMISSIONED_TAIL]
    late = wells[len(wells) - NOT_COMMISSIONED_TAIL :]
    roles = {
        well: (Role.INJ if index % _INJECTOR_SHARE == 0 else Role.PROD)
        for index, well in enumerate(commissioned)
    }
    roles.update({well: Role.NONE for well in late})
    return roles


def initial_state(
    wells: tuple[str, ...], roles: dict[str, Role], rng: Rng
) -> dict[str, WellState]:
    state: dict[str, WellState] = {}
    for well in wells:
        role = roles[well]
        if role is Role.NONE:
            state[well] = WellState(
                availability=Availability.NOT_COMMISSIONED,
                role=Role.NONE,
                operating_status=OperatingStatus.SHUT,
                setpoint=0.0,
            )
            continue
        setpoint = rng.between(120.0, 200.0) if role is Role.INJ else rng.between(40.0, 110.0)
        state[well] = WellState(
            availability=Availability.AVAILABLE,
            role=role,
            operating_status=OperatingStatus.OPEN,
            setpoint=round(setpoint, 1),
        )
    return state


def control_events(
    wells: tuple[str, ...], roles: dict[str, Role], n_intervals: int, rng: Rng
) -> tuple[ControlEvent, ...]:
    events: list[ControlEvent] = []
    actors = [well for well in wells if roles[well] is not Role.NONE]
    for step in range(n_intervals):
        well = actors[step % len(actors)]
        if roles[well] is Role.INJ:
            events.append(
                ControlEvent(
                    control_step=step,
                    well=well,
                    kind=EventKind.SET_RATE,
                    value=round(rng.between(120.0, 210.0), 1),
                )
            )
            continue
        events.append(
            ControlEvent(
                control_step=step,
                well=well,
                kind=EventKind.SET_LRAT,
                value=round(rng.between(35.0, 115.0), 1),
            )
        )
    return tuple(events)
