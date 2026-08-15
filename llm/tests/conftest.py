from __future__ import annotations

from datetime import date
from typing import Sequence

import pytest

from contracts import (
    ActiveControlMode,
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    Groups,
    IntervalResponse,
    Lambda,
    LineItems,
    NpvTable,
    OperatingStatus,
    Role,
    Rule,
    RunArtifact,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    TraceEntry,
    WellState,
)

PLACEHOLDER_HASH = "f" * 64

INJECTOR = "inj-alpha"
PRODUCER = "prod-beta"
PRODUCER_TWO = "prod-gamma"

WELLS = (INJECTOR, PRODUCER, PRODUCER_TWO)


def make_schedule(n_control_dates: int = 7) -> Schedule:
    initial_state = {
        INJECTOR: WellState(
            availability=Availability.AVAILABLE,
            role=Role.INJ,
            operating_status=OperatingStatus.OPEN,
            setpoint=150.0,
        ),
        PRODUCER: WellState(
            availability=Availability.AVAILABLE,
            role=Role.PROD,
            operating_status=OperatingStatus.OPEN,
            setpoint=80.0,
        ),
        PRODUCER_TWO: WellState(
            availability=Availability.AVAILABLE,
            role=Role.PROD,
            operating_status=OperatingStatus.OPEN,
            setpoint=70.0,
        ),
    }
    meta = ScheduleMeta(
        model="Model_Z",
        t0=date(2007, 1, 1),
        n_control_dates=n_control_dates,
        n_intervals=n_control_dates - 1,
        wells=tuple(sorted(WELLS)),
        history_prefix_hash=PLACEHOLDER_HASH,
        fixed_events_hash=PLACEHOLDER_HASH,
        control_events_hash=PLACEHOLDER_HASH,
        provenance="synthetic-llm-tests",
    )
    control_events = (
        ControlEvent(
            control_step=0, well=PRODUCER, kind=EventKind.SET_LRAT, value=55.0
        ),
        ControlEvent(
            control_step=1, well=INJECTOR, kind=EventKind.SET_RATE, value=160.0
        ),
    )
    return Schedule(
        meta=meta,
        initial_state=initial_state,
        fixed_deck_events=(),
        control_events=control_events,
    )


def make_interval_rows(
    well: str,
    oil: Sequence[float],
    liquid: Sequence[float],
    injection: Sequence[float],
) -> list[IntervalResponse]:
    return [
        IntervalResponse(
            control_step=step,
            well=well,
            oil_mass_delta=oil[step],
            liquid_volume_delta=liquid[step],
            injection_volume_delta=injection[step],
        )
        for step in range(len(oil))
    ]


def make_state_rows(
    well: str,
    liquid_rates: Sequence[float],
    bhp: Sequence[float],
) -> list[StateAtDate]:
    return [
        StateAtDate(
            deck_date_index=index,
            well=well,
            liquid_rate=liquid_rates[index],
            oil_rate=liquid_rates[index] * 0.3,
            injection_rate=0.0,
            thp=15.0,
            bhp=bhp[index],
            well_efficiency=0.95,
            active_control_mode=ActiveControlMode.RATE_TARGET,
        )
        for index in range(len(liquid_rates))
    ]


def _line_items() -> LineItems:
    return LineItems(
        revenue=1000.0,
        deductions=350.0,
        opex_oil=20.0,
        opex_liquid=30.0,
        opex_injection=10.0,
        opex_wellstock=50.0,
        property_tax=2.0,
        event_costs=1.0,
        capex_esp=4.0,
        ebitda=537.0,
        income_tax=134.25,
        fcf=398.75,
        df=0.9,
        discounted_fcf=358.875,
    )


def make_artifact(
    trace: tuple[TraceEntry, ...],
    interval_response: tuple[IntervalResponse, ...] = (),
    state_at_date: tuple[StateAtDate, ...] = (),
) -> RunArtifact:
    schedule = make_schedule()
    npv_table = NpvTable(
        by_year={2007: _line_items()},
        by_month={0: _line_items()},
        by_well={well: _line_items() for well in WELLS},
        npv_methodology=12345.0,
    )
    groups = Groups(
        groups={"G-alpha": tuple(sorted(WELLS))},
        lambda_hash=PLACEHOLDER_HASH,
        group_hash=PLACEHOLDER_HASH,
    )
    lambda_ = Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2008, 1, 1),
        producers=(PRODUCER, PRODUCER_TWO),
        injectors=(INJECTOR,),
        matrix=((0.2,), (0.1,)),
        lag_months=2,
        amplitude=0.15,
        stability=0.8,
        rank=1,
        condition_number=3.5,
        achievability_ok={INJECTOR: True},
    )
    return RunArtifact(
        config_hash=PLACEHOLDER_HASH,
        schedule=schedule,
        state_at_date=state_at_date,
        interval_response=interval_response,
        npv_table=npv_table,
        trace=trace,
        groups=groups,
        lambda_=lambda_,
        constraints=Constraints(),
        converged=True,
        self_consistent=True,
        final_npv=None,
    )


@pytest.fixture
def schedule() -> Schedule:
    return make_schedule()


@pytest.fixture
def trace_entry() -> TraceEntry:
    return TraceEntry(
        control_step=3,
        well=PRODUCER,
        rule=Rule.R2,
        inputs={"watercut": 0.87, "liquid_rate": 72.5},
        decision="SET_LRAT 45.5",
    )
