from __future__ import annotations

from datetime import date

from aios_backend.core.contracts import (
    ActiveControlMode,
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
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
    WellOutage,
    WellState,
)

SYNTHETIC_PROVENANCE = "synthetic-fixture"
_PLACEHOLDER_HASH = "0" * 64


def _line_items(seed: float) -> LineItems:
    revenue = 1_000_000.0 + seed
    deductions = 0.35 * revenue
    opex_oil = 0.02 * revenue
    opex_liquid = 0.03 * revenue
    opex_injection = 0.01 * revenue
    opex_wellstock = 0.05 * revenue
    property_tax = 0.002 * revenue
    event_costs = 0.001 * revenue
    capex_esp = 0.004 * revenue
    ebitda = revenue - deductions - opex_oil - opex_liquid - opex_injection - opex_wellstock - property_tax - event_costs
    income_tax = 0.25 * max(0.0, ebitda)
    fcf = ebitda - income_tax - capex_esp
    df = 0.9
    return LineItems(
        revenue=revenue,
        deductions=deductions,
        opex_oil=opex_oil,
        opex_liquid=opex_liquid,
        opex_injection=opex_injection,
        opex_wellstock=opex_wellstock,
        property_tax=property_tax,
        event_costs=event_costs,
        capex_esp=capex_esp,
        ebitda=ebitda,
        income_tax=income_tax,
        fcf=fcf,
        df=df,
        discounted_fcf=fcf * df,
    )


def _state_row(deck_date_index: int, well: str, role: Role, commissioned: bool, offset: float) -> StateAtDate:
    if not commissioned:
        return StateAtDate(
            deck_date_index=deck_date_index,
            well=well,
            liquid_rate=0.0,
            oil_rate=0.0,
            injection_rate=0.0,
            thp=0.0,
            bhp=0.0,
            well_efficiency=0.0,
            active_control_mode=ActiveControlMode.NOT_COMMISSIONED,
        )
    if role is Role.INJ:
        return StateAtDate(
            deck_date_index=deck_date_index,
            well=well,
            liquid_rate=0.0,
            oil_rate=0.0,
            injection_rate=140.0 + deck_date_index + offset,
            thp=20.0,
            bhp=250.0,
            well_efficiency=0.95,
            active_control_mode=ActiveControlMode.RATE_TARGET,
        )
    return StateAtDate(
        deck_date_index=deck_date_index,
        well=well,
        liquid_rate=70.0 + deck_date_index + offset,
        oil_rate=20.0 + 0.5 * deck_date_index + offset,
        injection_rate=0.0,
        thp=15.0,
        bhp=90.0,
        well_efficiency=0.97,
        active_control_mode=ActiveControlMode.RATE_TARGET,
    )


def _interval_row(control_step: int, well: str, role: Role, commissioned: bool, offset: float) -> IntervalResponse:
    if not commissioned:
        return IntervalResponse(
            control_step=control_step,
            well=well,
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=0.0,
        )
    if role is Role.INJ:
        return IntervalResponse(
            control_step=control_step,
            well=well,
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=4000.0 + 10.0 * control_step + offset,
        )
    return IntervalResponse(
        control_step=control_step,
        well=well,
        oil_mass_delta=600.0 + 5.0 * control_step + offset,
        liquid_volume_delta=2100.0 + 20.0 * control_step + offset,
        injection_volume_delta=0.0,
    )


def make_synthetic_artifact(
    n_wells: int = 5, n_deck_dates: int = 12, n_control_dates: int = 7
) -> RunArtifact:
    if n_wells < 3:
        raise ValueError("n_wells >= 3: нужны нагнетательная, добывающая и невведённая")
    if n_control_dates < 3:
        raise ValueError("n_control_dates >= 3")
    if n_deck_dates < n_control_dates:
        raise ValueError("n_deck_dates >= n_control_dates")

    n_intervals = n_control_dates - 1
    wells = tuple(sorted(str(10 + i) for i in range(n_wells)))
    inj_well = wells[0]
    nc_well = wells[-1]
    producers = wells[1:-1]

    def role_of(well: str) -> Role:
        if well == inj_well:
            return Role.INJ
        if well == nc_well:
            return Role.NONE
        return Role.PROD

    def commissioned(well: str) -> bool:
        return well != nc_well

    initial_state = {
        well: WellState(
            availability=Availability.AVAILABLE if commissioned(well) else Availability.NOT_COMMISSIONED,
            role=role_of(well),
            operating_status=OperatingStatus.OPEN if commissioned(well) else OperatingStatus.SHUT,
            setpoint=(150.0 if role_of(well) is Role.INJ else 80.0) if commissioned(well) else 0.0,
        )
        for well in wells
    }

    meta = ScheduleMeta(
        model="Model_Z",
        t0=date(2007, 1, 1),
        n_control_dates=n_control_dates,
        n_intervals=n_intervals,
        wells=wells,
        history_prefix_hash=_PLACEHOLDER_HASH,
        fixed_events_hash=_PLACEHOLDER_HASH,
        control_events_hash=_PLACEHOLDER_HASH,
        provenance=SYNTHETIC_PROVENANCE,
    )

    fixed_deck_events = (
        FixedDeckEvent(
            control_step=0,
            well=producers[0],
            operator="COMPDAT",
            raw_args=("10", "10", "3", "5", "OPEN"),
        ),
        FixedDeckEvent(
            control_step=min(1, n_intervals - 1),
            well=inj_well,
            operator="WPIMULT",
            raw_args=("0.8",),
        ),
    )

    control_events = tuple(
        [ControlEvent(control_step=0, well=inj_well, kind=EventKind.SET_RATE, value=160.0)]
        + [
            ControlEvent(
                control_step=k,
                well=producers[k % len(producers)],
                kind=EventKind.SET_LRAT,
                value=50.0 + k,
            )
            for k in range(n_intervals)
        ]
    )

    schedule = Schedule(
        meta=meta,
        initial_state=initial_state,
        fixed_deck_events=fixed_deck_events,
        control_events=control_events,
    )

    state_at_date = tuple(
        _state_row(d, well, role_of(well), commissioned(well), float(i))
        for d in range(n_deck_dates)
        for i, well in enumerate(wells)
    )

    interval_response = tuple(
        _interval_row(k, well, role_of(well), commissioned(well), float(i))
        for k in range(n_intervals)
        for i, well in enumerate(wells)
    )

    by_month = {k: _line_items(1000.0 * k) for k in range(n_intervals)}
    by_year = {2007: _line_items(50_000.0), 2008: _line_items(60_000.0)}
    by_well = {well: _line_items(100.0 * i) for i, well in enumerate(wells)}
    npv_table = NpvTable(
        by_year=by_year,
        by_month=by_month,
        by_well=by_well,
        npv_methodology=123_456_789.0,
    )

    trace = (
        TraceEntry(
            control_step=0,
            well=producers[0],
            rule=Rule.R1,
            inputs={"watercut": 0.83, "liquid_rate": 72.0},
            decision="SET_LRAT 50.0",
        ),
        TraceEntry(
            control_step=n_intervals - 1,
            well=inj_well,
            rule=Rule.R4,
            inputs={"injection_rate": 160.0},
            decision="SET_RATE 160.0",
        ),
    )

    groups = Groups(
        groups={"G1": wells},
        lambda_hash=_PLACEHOLDER_HASH,
        group_hash=_PLACEHOLDER_HASH,
    )

    lambda_ = Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2008, 1, 1),
        producers=producers,
        injectors=(inj_well,),
        matrix=tuple((0.1 * (i + 1),) for i in range(len(producers))),
        lag_months=2,
        amplitude=0.15,
        stability=0.8,
        rank=1,
        condition_number=3.5,
        achievability_ok={inj_well: True},
    )

    constraints = Constraints(
        injection_limits={2007: 5000.0, 2008: 5200.0},
        liquid_limits={2007: 8000.0},
        production_floors={2008: 40.0},
        watercut_limits={2008: 0.95},
        well_outages=(
            WellOutage(
                well=producers[0],
                control_step_from=0,
                control_step_to=min(1, n_intervals - 1),
            ),
        ),
        infrastructure={"kns_limit_m3_per_day": 12_000.0},
    )

    return RunArtifact(
        config_hash=_PLACEHOLDER_HASH,
        schedule=schedule,
        state_at_date=state_at_date,
        interval_response=interval_response,
        npv_table=npv_table,
        trace=trace,
        groups=groups,
        lambda_=lambda_,
        constraints=constraints,
        converged=True,
        self_consistent=True,
        final_npv=None,
    )
