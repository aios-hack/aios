from __future__ import annotations

import pytest

from backend.core.contracts import (
    Constraints,
    compensation_policy,
    water_supply_policy,
)


def test_water_supply_is_disabled_only_when_no_water_keys_are_present() -> None:
    assert not water_supply_policy(Constraints()).enabled
    with pytest.raises(ValueError, match="water_reinjection_fraction"):
        water_supply_policy(
            Constraints(infrastructure={"external_water_m3_per_day": 1.0})
        )


@pytest.mark.parametrize("fraction", [-0.01, 1.01, float("inf")])
def test_water_reinjection_fraction_is_a_physical_fraction(fraction: float) -> None:
    with pytest.raises(ValueError):
        water_supply_policy(
            Constraints(infrastructure={"water_reinjection_fraction": fraction})
        )


def test_water_limit_combines_reinjection_and_explicit_external_source() -> None:
    policy = water_supply_policy(
        Constraints(
            infrastructure={
                "water_reinjection_fraction": 0.8,
                "water_reinjection_lag_steps": 1,
                "external_water_m3_per_day": 5.0,
            }
        )
    )
    assert policy.enabled
    assert policy.lag_steps == 1
    assert policy.limit(100.0) == pytest.approx(85.0)


def test_compensation_corridor_is_complete_and_ordered() -> None:
    with pytest.raises(ValueError, match="compensation_max"):
        compensation_policy(
            Constraints(infrastructure={"compensation_min": 0.85})
        )
    with pytest.raises(ValueError, match="коридор компенсации пуст"):
        compensation_policy(
            Constraints(
                infrastructure={"compensation_min": 1.15, "compensation_max": 0.85}
            )
        )


def test_compensation_contract_parses_hackathon_defaults() -> None:
    policy = compensation_policy(
        Constraints(
            infrastructure={
                "compensation_min": 0.85,
                "compensation_max": 1.15,
                "compensation_enforcement": "diagnostic",
                "compensation_scope": "field_and_groups",
            }
        )
    )
    assert policy.enabled
    assert not policy.hard
    assert policy.minimum == pytest.approx(0.85)
    assert policy.maximum == pytest.approx(1.15)
