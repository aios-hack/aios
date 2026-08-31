from __future__ import annotations

import pytest

from backend.application.optimization.schedule_search import (
    _field_limit_for_step,
    _flow_start_steps,
    _outage_events,
    _scale_step_injection_to_limit,
)
from backend.core.contracts import (
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from backend.domain.policy.state import PolicyState, WellObservation


def _observation(well: str, role: Role) -> WellObservation:
    return WellObservation(
        well=well,
        role=role,
        is_open=True,
        liquid_rate_m3_per_day=0.0,
        oil_rate_t_per_day=0.0,
        injection_rate_m3_per_day=0.0,
        setpoint_m3_per_day=0.0,
    )


def test_field_limit_intersects_physics_case_and_available_water() -> None:
    constraints = Constraints(
        injection_limits={2007: 50.0},
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "external_water_m3_per_day": 5.0,
        },
    )
    assert _field_limit_for_step(
        physical_limit_m3_per_day=100.0,
        constraints=constraints,
        year=2007,
        control_step=0,
        produced_water_by_step=[40.0],
    ) == pytest.approx(45.0)


def test_lagged_water_has_only_external_source_on_first_step() -> None:
    constraints = Constraints(
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "water_reinjection_lag_steps": 1,
            "external_water_m3_per_day": 5.0,
        }
    )
    assert _field_limit_for_step(
        physical_limit_m3_per_day=100.0,
        constraints=constraints,
        year=2007,
        control_step=0,
        produced_water_by_step=[40.0],
    ) == pytest.approx(5.0)


def test_dense_injection_layer_is_scaled_to_available_water() -> None:
    pending = {
        (0, "I1", EventKind.SET_RATE): ControlEvent(0, "I1", EventKind.SET_RATE, 80.0),
        (0, "I1", EventKind.OPEN): ControlEvent(0, "I1", EventKind.OPEN),
        (0, "I2", EventKind.SET_RATE): ControlEvent(0, "I2", EventKind.SET_RATE, 20.0),
    }
    current_open = {"I1": True, "I2": True}
    current_setpoint = {"I1": 80.0, "I2": 20.0}
    total = _scale_step_injection_to_limit(
        pending,
        0,
        50.0,
        current_is_open=current_open,
        current_setpoint=current_setpoint,
    )
    assert total == pytest.approx(50.0)
    assert pending[(0, "I1", EventKind.SET_RATE)].value == pytest.approx(40.0)
    assert pending[(0, "I2", EventKind.SET_RATE)].value == pytest.approx(10.0)


def test_water_scaling_quantizes_down_so_it_never_creates_water() -> None:
    pending = {
        (0, "I1", EventKind.SET_RATE): ControlEvent(0, "I1", EventKind.SET_RATE, 2.0),
        (0, "I2", EventKind.SET_RATE): ControlEvent(0, "I2", EventKind.SET_RATE, 1.0),
    }
    current_open = {"I1": True, "I2": True}
    current_setpoint = {"I1": 2.0, "I2": 1.0}

    total = _scale_step_injection_to_limit(
        pending,
        0,
        2.5,
        current_is_open=current_open,
        current_setpoint=current_setpoint,
    )

    assert total == 1.0
    assert total <= 2.5
    assert all(float(event.value or 0.0).is_integer() for event in pending.values())


def test_outage_forces_zero_target_and_shut() -> None:
    state = PolicyState(control_step=3, wells={"I1": _observation("I1", Role.INJ)})
    events = _outage_events(state, frozenset({"I1"}))
    assert [(event.kind, event.value) for event in events] == [
        (EventKind.SET_RATE, 0.0),
        (EventKind.SHUT, None),
    ]


@pytest.mark.parametrize("operator", ["COMPDAT", "COMPDATMD"])
def test_flow_starts_only_after_first_completion(operator: str) -> None:
    schedule = Schedule(
        meta=ScheduleMeta(wells=("P1",)),
        initial_state={
            "P1": WellState(
                availability=Availability.NOT_COMMISSIONED,
                role=Role.NONE,
                operating_status=OperatingStatus.SHUT,
                setpoint=0.0,
            )
        },
        fixed_deck_events=(
            FixedDeckEvent(0, "P1", "WCONPROD", ("OPEN",)),
            FixedDeckEvent(60, "P1", operator, ("1", "1")),
        ),
        control_events=(),
    )

    assert _flow_start_steps(schedule, {"P1": (0.0, 0.0, 0.0)}) == {"P1": 60}
