from __future__ import annotations

import math

from backend.contexts.schedule.domain.schedule import (
    Availability,
    EventKind,
    OperatingStatus,
    Role,
    WellState,
)

CONTROL_ORDER = {
    EventKind.SET_LRAT: 0,
    EventKind.CONVERT_INJ: 1,
    EventKind.SET_RATE: 2,
    EventKind.OPEN: 3,
    EventKind.SHUT: 3,
}


def commissioning_state(operator: str, raw_args: tuple[str, ...]) -> WellState:
    if operator == "WCONPROD":
        if len(raw_args) < 6 or raw_args[1] != "LRAT":
            raise ValueError("WCONPROD: LRAT mode expected")
        role, status, target = Role.PROD, raw_args[0], raw_args[5]
    elif operator == "WCONINJE":
        if len(raw_args) < 4 or raw_args[0] != "WATER" or raw_args[2] != "RATE":
            raise ValueError("WCONINJE: WATER/RATE expected")
        role, status, target = Role.INJ, raw_args[1], raw_args[3]
    else:
        raise ValueError(f"{operator}: is not a commissioning event")
    value = float(target)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid setpoint: {target!r}")
    return WellState(
        availability=Availability.AVAILABLE, role=role,
        operating_status=OperatingStatus(status), setpoint=value,
    )
