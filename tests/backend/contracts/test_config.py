import pytest

from backend.contexts.constraints.domain.config import (
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
)


def _base() -> NormativeSet:
    return NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=())


def test_normatives_match_reference_calculator() -> None:
    base = _base()
    assert base.price_oil_rub_per_t == 28_000.0
    assert base.deductions_rub_per_t == 19_600.0
    assert base.opex_oil_rub_per_t == 40.0
    assert base.opex_liquid_rub_per_t == 100.0
    assert base.opex_injection_rub_per_m3 == 30.0
    assert base.opex_wellstock_rub_per_well_year == 1_000_000.0
    assert base.esp_swap_opex_rub == 1_800_000.0
    assert base.event_cost_rub == 1_000_000.0
    assert base.conversion_base_cost_rub == 5_000_000.0
    assert base.wacc == 0.10
    assert base.property_tax_rate == 0.022
    assert base.income_tax_rate == 0.25


def test_oil_margin_is_8360_rub_per_t() -> None:
    base = _base()
    margin = base.price_oil_rub_per_t - base.deductions_rub_per_t - base.opex_oil_rub_per_t
    assert margin == 8_360.0


def test_conversion_cost_carries_no_esp() -> None:
    assert _base().conversion_base_cost_rub == 5_000_000.0


def test_initial_esp_default_is_not_charged() -> None:
    assert ChargeInitialEsp.NOT_CHARGED.value == "NOT_CHARGED"
    assert len(ChargeInitialEsp) == 2


def test_normatives_have_no_year_axis() -> None:
    assert not hasattr(NormativeSet, "for_year")
    with pytest.raises(TypeError):
        NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=(), by_year={})  # type: ignore[call-arg]
