from __future__ import annotations

import pytest

from backend.core.contracts import (
    Constraints,
    compensation_policy,
    water_supply_policy,
)
from backend.contexts.constraints.domain.constraints import (
    BHP_INJECTOR_MAX_BAR,
    BHP_PRODUCER_MIN_BAR,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    DEFAULT_BHP_INJECTOR_MAX_BAR,
    DEFAULT_BHP_PRODUCER_MIN_BAR,
    SOURCE_DIAGNOSTIC,
    SOURCE_ORGANIZER,
    bhp_limits,
    constraint_source,
    limit_origin,
    source_key,
)


def test_water_supply_is_disabled_only_when_no_water_keys_are_present() -> None:
    policy = water_supply_policy(Constraints())
    assert not policy.enabled
    assert not policy.unlimited
    assert not policy.fraction_defaulted


def test_external_water_alone_defaults_the_reinjection_fraction_to_one() -> None:
    policy = water_supply_policy(
        Constraints(infrastructure={"external_water_m3_per_day": 5000.0})
    )
    assert policy.enabled
    assert not policy.unlimited
    assert policy.reinjection_fraction == pytest.approx(1.0)
    assert policy.fraction_defaulted
    assert policy.external_water_m3_per_day == pytest.approx(5000.0)
    assert policy.limit(100.0) == pytest.approx(5100.0)


def test_explicit_fraction_is_not_marked_as_defaulted() -> None:
    policy = water_supply_policy(
        Constraints(
            infrastructure={
                "external_water_m3_per_day": 5000.0,
                "water_reinjection_fraction": 0.4,
            }
        )
    )
    assert policy.enabled
    assert not policy.fraction_defaulted
    assert policy.reinjection_fraction == pytest.approx(0.4)


def test_unlimited_water_supply_disables_the_source_limit() -> None:
    policy = water_supply_policy(
        Constraints(infrastructure={"water_supply_unlimited": True})
    )
    assert not policy.enabled
    assert policy.unlimited
    assert not policy.fraction_defaulted
    assert policy.limit(100.0) is None


def test_unlimited_water_supply_contradicts_an_external_volume() -> None:
    with pytest.raises(ValueError, match="water_supply_unlimited"):
        water_supply_policy(
            Constraints(
                infrastructure={
                    "water_supply_unlimited": True,
                    "external_water_m3_per_day": 5000.0,
                }
            )
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
    assert not policy.fraction_defaulted
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


def test_bhp_limits_fall_back_to_the_deck_defaults() -> None:
    limits = bhp_limits(Constraints())
    assert limits.producer_min_bar == pytest.approx(DEFAULT_BHP_PRODUCER_MIN_BAR)
    assert limits.injector_max_bar == pytest.approx(DEFAULT_BHP_INJECTOR_MAX_BAR)
    assert limits.producer_min_defaulted
    assert limits.injector_max_defaulted


def test_bhp_limits_come_from_the_case_when_declared() -> None:
    limits = bhp_limits(
        Constraints(
            infrastructure={
                BHP_PRODUCER_MIN_BAR: 90.0,
                BHP_INJECTOR_MAX_BAR: 260.0,
            }
        )
    )
    assert limits.producer_min_bar == pytest.approx(90.0)
    assert limits.injector_max_bar == pytest.approx(260.0)
    assert not limits.producer_min_defaulted
    assert not limits.injector_max_defaulted


def test_empty_bhp_corridor_is_refused() -> None:
    with pytest.raises(ValueError, match="коридор забойного давления пуст"):
        bhp_limits(
            Constraints(
                infrastructure={
                    BHP_PRODUCER_MIN_BAR: 300.0,
                    BHP_INJECTOR_MAX_BAR: 300.0,
                }
            )
        )


def test_declared_source_is_available_to_the_consumer() -> None:
    constraints = Constraints(
        infrastructure={
            BHP_PRODUCER_MIN_BAR: 60.0,
            source_key(BHP_PRODUCER_MIN_BAR): SOURCE_ORGANIZER,
        }
    )
    assert constraint_source(constraints, BHP_PRODUCER_MIN_BAR) == SOURCE_ORGANIZER


def test_declared_limit_without_a_source_reports_no_source() -> None:
    constraints = Constraints(infrastructure={BHP_PRODUCER_MIN_BAR: 60.0})
    assert constraint_source(constraints, BHP_PRODUCER_MIN_BAR) is None


def test_unset_bhp_limit_keeps_the_deck_source() -> None:
    assert constraint_source(Constraints(), BHP_PRODUCER_MIN_BAR) == SOURCE_ORGANIZER


def test_unknown_source_value_is_refused() -> None:
    constraints = Constraints(
        infrastructure={
            BHP_PRODUCER_MIN_BAR: 60.0,
            source_key(BHP_PRODUCER_MIN_BAR): "нашлось",
        }
    )
    with pytest.raises(ValueError, match="bhp_producer_min_bar_source"):
        constraint_source(constraints, BHP_PRODUCER_MIN_BAR)


def test_limit_origin_names_the_source_and_the_case_file() -> None:
    constraints = Constraints(
        infrastructure={
            COMPENSATION_MIN: 0.85,
            COMPENSATION_MAX: 1.15,
            source_key(COMPENSATION_MIN): SOURCE_DIAGNOSTIC,
        },
        case_path="config/cases/base.json",
    )
    origin = limit_origin(constraints, COMPENSATION_MIN)
    assert SOURCE_DIAGNOSTIC in origin
    assert "config/cases/base.json" in origin
