from __future__ import annotations

from aios_backend.core.contracts import (  # noqa: E402
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from aios_backend.ml.surrogate.schedule_roles import build_role_timelines


def _schedule() -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("LATE", "P")),
        initial_state={
            "LATE": WellState(
                availability=Availability.NOT_COMMISSIONED,
                role=Role.NONE,
                operating_status=OperatingStatus.SHUT,
                setpoint=0.0,
            ),
            "P": WellState(
                availability=Availability.AVAILABLE,
                role=Role.PROD,
                operating_status=OperatingStatus.OPEN,
                setpoint=20.0,
            ),
        },
        fixed_deck_events=(
            FixedDeckEvent(
                control_step=5,
                well="LATE",
                operator="WCONINJE",
                raw_args=("'LATE' WATER OPEN RATE 30" ,),
            ),
        ),
        control_events=(
            ControlEvent(control_step=10, well="P", kind=EventKind.CONVERT_INJ),
        ),
    )


def test_role_timeline_tracks_fixed_commissioning_and_managed_conversion() -> None:
    timelines = build_role_timelines(_schedule())

    assert timelines["LATE"].role(4) is Role.NONE
    assert timelines["LATE"].role(5) is Role.INJ
    assert timelines["P"].role(9) is Role.PROD
    assert timelines["P"].role(10) is Role.INJ


def test_role_timeline_covers_every_declared_well() -> None:
    timelines = build_role_timelines(_schedule())

    assert set(timelines) == {"LATE", "P"}
