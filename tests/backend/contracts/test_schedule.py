import pytest

from backend.contexts.schedule.domain.schedule import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    WellState,
)


def test_not_commissioned_normalization_ok() -> None:
    ws = WellState(
        availability=Availability.NOT_COMMISSIONED,
        role=Role.NONE,
        operating_status=OperatingStatus.SHUT,
        setpoint=0.0,
    )
    assert ws.setpoint == 0.0


@pytest.mark.parametrize(
    "role,status,setpoint",
    [
        (Role.PROD, OperatingStatus.SHUT, 0.0),
        (Role.NONE, OperatingStatus.OPEN, 0.0),
        (Role.NONE, OperatingStatus.SHUT, 5.0),
    ],
)
def test_not_commissioned_normalization_rejects_deviation(role, status, setpoint) -> None:
    with pytest.raises(ValueError):
        WellState(
            availability=Availability.NOT_COMMISSIONED,
            role=role,
            operating_status=status,
            setpoint=setpoint,
        )


def test_available_well_state_any_role_ok() -> None:
    WellState(
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.OPEN,
        setpoint=25.0,
    )


def test_control_event_step_domain() -> None:
    ControlEvent(control_step=223, well="42", kind=EventKind.OPEN)
    with pytest.raises(ValueError):
        ControlEvent(control_step=224, well="42", kind=EventKind.OPEN)


def test_control_event_value_required_for_set_lrat() -> None:
    with pytest.raises(ValueError):
        ControlEvent(control_step=0, well="42", kind=EventKind.SET_LRAT)
    ControlEvent(control_step=0, well="42", kind=EventKind.SET_LRAT, value=20.0)


def test_control_event_open_rejects_value() -> None:
    with pytest.raises(ValueError):
        ControlEvent(control_step=0, well="42", kind=EventKind.OPEN, value=1.0)


def test_set_lrat_rejects_above_methodology_ceiling() -> None:
    ControlEvent(control_step=0, well="42", kind=EventKind.SET_LRAT, value=500.0)
    with pytest.raises(ValueError, match="500"):
        ControlEvent(control_step=0, well="42", kind=EventKind.SET_LRAT, value=500.1)


def test_setpoints_reject_negative_values() -> None:
    for kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
        with pytest.raises(ValueError):
            ControlEvent(control_step=0, well="42", kind=kind, value=-1.0)


def test_injection_rate_is_not_capped_by_lrat_ceiling() -> None:
    ControlEvent(control_step=0, well="49", kind=EventKind.SET_RATE, value=900.0)
