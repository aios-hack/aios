from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from aios_backend.core.contracts import (
    DEFAULT_NORMATIVES_2007,
    EspCatalogEntry,
    Groups,
    Lambda,
    NormativeSet,
    Role,
)

from aios_backend.domain.policy import PolicyMemory, PolicyState, RuleContext, WellMemory, WellObservation

ESP_CATALOG: tuple[EspCatalogEntry, ...] = (
    EspCatalogEntry(nominal=20.0, interval_low=0.0, interval_high=25.0, cost_rub=900_000.0),
    EspCatalogEntry(nominal=45.0, interval_low=25.0, interval_high=60.0, cost_rub=1_400_000.0),
    EspCatalogEntry(nominal=80.0, interval_low=60.0, interval_high=95.0, cost_rub=2_100_000.0),
    EspCatalogEntry(nominal=125.0, interval_low=95.0, interval_high=160.0, cost_rub=3_300_000.0),
)

OIL_DENSITY_T_PER_M3 = 0.9131
OIL_DENSITY_SECOND_REGION_T_PER_M3 = 0.9282


@pytest.fixture
def normatives() -> NormativeSet:
    return NormativeSet(esp_catalog=ESP_CATALOG, **DEFAULT_NORMATIVES_2007)


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


def groups_of(mapping: dict[str, tuple[str, ...]]) -> Groups:
    return Groups(
        groups=mapping,
        lambda_hash="a" * 64,
        group_hash="b" * 64,
    )


def memory_of(**by_well: WellMemory) -> PolicyMemory:
    return PolicyMemory(wells=dict(by_well))


DECIDING_WELLS = (
    producer("42", liquid_rate_m3_per_day=5.0, watercut=0.99, setpoint=5.0),
    producer("43", liquid_rate_m3_per_day=40.0, watercut=0.40, setpoint=90.0),
    injector("101", injection_rate_m3_per_day=200.0),
)


def deciding_context(context: RuleContext) -> RuleContext:
    influence = influence_of(
        producers=("42", "43"),
        injectors=("101", "43"),
        matrix=((0.4, 3.0), (0.7, 3.0)),
    )
    return replace(
        context,
        influence=influence,
        injection_budget_m3_per_day=300.0,
        groups=groups_of({"G1": ("42", "43", "101")}),
        group_injection_m3_per_day={"G1": 200.0},
        group_offtake_m3_per_day={"G1": 45.0},
        memory=memory_of(),
    )
