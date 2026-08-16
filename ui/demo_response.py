from __future__ import annotations

from contracts import ActiveControlMode, IntervalResponse, Role, StateAtDate

from ui.demo_rng import Rng


def state_rows(
    wells: tuple[str, ...],
    roles: dict[str, Role],
    n_deck_dates: int,
    commission_step: dict[str, int],
    offset: int,
    rng: Rng,
) -> tuple[StateAtDate, ...]:
    rows: list[StateAtDate] = []
    base = {well: rng.between(0.6, 1.4) for well in wells}
    for index in range(n_deck_dates):
        decline = 1.0 - 0.45 * (index / max(1, n_deck_dates - 1))
        for well in wells:
            role = roles[well]
            live = index >= offset + commission_step.get(well, 0)
            if role is Role.NONE and not live:
                rows.append(
                    StateAtDate(
                        deck_date_index=index,
                        well=well,
                        liquid_rate=0.0,
                        oil_rate=0.0,
                        injection_rate=0.0,
                        thp=0.0,
                        bhp=0.0,
                        well_efficiency=0.0,
                        active_control_mode=ActiveControlMode.NOT_COMMISSIONED,
                    )
                )
                continue
            scale = base[well] * decline
            if role is Role.INJ:
                rows.append(
                    StateAtDate(
                        deck_date_index=index,
                        well=well,
                        liquid_rate=0.0,
                        oil_rate=0.0,
                        injection_rate=round(150.0 * scale, 2),
                        thp=round(22.0 * scale, 2),
                        bhp=round(245.0 * scale, 2),
                        well_efficiency=0.95,
                        active_control_mode=ActiveControlMode.RATE_TARGET,
                    )
                )
                continue
            liquid = 85.0 * scale
            rows.append(
                StateAtDate(
                    deck_date_index=index,
                    well=well,
                    liquid_rate=round(liquid, 2),
                    oil_rate=round(liquid * 0.28 * decline, 2),
                    injection_rate=0.0,
                    thp=round(16.0 * scale, 2),
                    bhp=round(95.0 * scale, 2),
                    well_efficiency=0.97,
                    active_control_mode=ActiveControlMode.RATE_TARGET,
                )
            )
    return tuple(rows)


def interval_rows(
    wells: tuple[str, ...],
    roles: dict[str, Role],
    n_intervals: int,
    commission_step: dict[str, int],
    rng: Rng,
) -> tuple[IntervalResponse, ...]:
    rows: list[IntervalResponse] = []
    base = {well: rng.between(0.7, 1.3) for well in wells}
    for step in range(n_intervals):
        decline = 1.0 - 0.45 * (step / max(1, n_intervals - 1))
        for well in wells:
            role = roles[well]
            if step < commission_step.get(well, 0):
                rows.append(
                    IntervalResponse(
                        control_step=step,
                        well=well,
                        oil_mass_delta=0.0,
                        liquid_volume_delta=0.0,
                        injection_volume_delta=0.0,
                    )
                )
                continue
            scale = base[well] * decline
            if role is Role.INJ:
                rows.append(
                    IntervalResponse(
                        control_step=step,
                        well=well,
                        oil_mass_delta=0.0,
                        liquid_volume_delta=0.0,
                        injection_volume_delta=round(4500.0 * scale, 2),
                    )
                )
                continue
            liquid = 2550.0 * scale
            rows.append(
                IntervalResponse(
                    control_step=step,
                    well=well,
                    oil_mass_delta=round(liquid * 0.26 * decline, 2),
                    liquid_volume_delta=round(liquid, 2),
                    injection_volume_delta=0.0,
                )
            )
    return tuple(rows)
