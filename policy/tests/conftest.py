from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from contracts import DEFAULT_NORMATIVES_2007, Lambda, NormativeSet, Role

from policy import PolicyState, RuleContext, WellObservation

OIL_DENSITY_T_PER_M3 = 0.9131
OIL_DENSITY_SECOND_REGION_T_PER_M3 = 0.9282


@pytest.fixture
def normatives() -> NormativeSet:
    return NormativeSet(esp_catalog=(), **DEFAULT_NORMATIVES_2007)


@pytest.fixture
def context(normatives: NormativeSet) -> RuleContext:
    return RuleContext(
        normatives=normatives,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )


def producer(
    well: str,
    liquid_rate_m3_per_day: float,
    watercut: float,
    density: float = OIL_DENSITY_T_PER_M3,
    setpoint: float | None = None,
    is_open: bool = True,
) -> WellObservation:
    oil_volume = liquid_rate_m3_per_day * (1.0 - watercut)
    return WellObservation(
        well=well,
        role=Role.PROD,
        is_open=is_open,
        liquid_rate_m3_per_day=liquid_rate_m3_per_day,
        oil_rate_t_per_day=oil_volume * density,
        injection_rate_m3_per_day=0.0,
        setpoint_m3_per_day=(
            liquid_rate_m3_per_day if setpoint is None else setpoint
        ),
    )


def injector(
    well: str, injection_rate_m3_per_day: float, setpoint: float | None = None
) -> WellObservation:
    return WellObservation(
        well=well,
        role=Role.INJ,
        is_open=True,
        liquid_rate_m3_per_day=0.0,
        oil_rate_t_per_day=0.0,
        injection_rate_m3_per_day=injection_rate_m3_per_day,
        setpoint_m3_per_day=(
            injection_rate_m3_per_day if setpoint is None else setpoint
        ),
    )


def state_of(*observations: WellObservation, control_step: int = 0) -> PolicyState:
    return PolicyState(
        control_step=control_step,
        wells={obs.well: obs for obs in observations},
    )


def influence_of(
    producers: tuple[str, ...],
    injectors: tuple[str, ...],
    matrix: tuple[tuple[float, ...], ...],
    lag_months: int = 3,
) -> Lambda:
    return Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2010, 1, 1),
        producers=producers,
        injectors=injectors,
        matrix=matrix,
        lag_months=lag_months,
        amplitude=25.0,
        stability=0.8,
        rank=len(injectors),
        condition_number=4.0,
        achievability_ok={well: True for well in injectors},
    )


def with_oil_price(normatives: NormativeSet, price_rub_per_t: float) -> NormativeSet:
    return replace(normatives, price_oil_rub_per_t=price_rub_per_t)
