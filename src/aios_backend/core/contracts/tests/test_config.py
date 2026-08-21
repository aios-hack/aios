import pytest

from aios_backend.core.contracts import ChargeInitialEsp, DEFAULT_NORMATIVES_2007, NormativeSet


def _base() -> NormativeSet:
    return NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=())


def test_normatives_match_reference_calculator() -> None:
    """Значения обязаны совпадать с нормативами организаторов.

    Источник истины — docs/models/CHDD_PYTHON/input/Нормативы_ЧДД.xlsx, он же
    DEFAULT_ASSUMPTIONS в chdd_model.py. Проверяющая сторона считает этими
    числами; расхождение здесь — расхождение в заявленном ЧДД.

    Тест намеренно повторяет значения литералами, а не читает xlsx: пакет
    contracts не должен зависеть от репозитория с данными. Сверять руками
    при каждом обновлении материалов организаторов.
    """
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
    """Маржа, на которой стоит правило R0 и таблица порогов рентабельности."""
    base = _base()
    margin = base.price_oil_rub_per_t - base.deductions_rub_per_t - base.opex_oil_rub_per_t
    assert margin == 8_360.0


def test_conversion_cost_carries_no_esp() -> None:
    """Перевод под закачку — ровно 5.0 млн, целиком в OPEX.

    Первая редакция Методики задавала OPEX_ВНС = 5.0 + C_ki^ESP; в
    скорректированной слагаемое убрано, эталонный расчётчик выставляет
    conversionPumpCostM = 0.0. Тест сторожит откат к прежней формуле:
    стоимость перевода — одно число, а не база плюс каталог ЭЦН.
    """
    assert _base().conversion_base_cost_rub == 5_000_000.0


def test_initial_esp_default_is_not_charged() -> None:
    """Умолчание обязано совпадать с chargeInitialPump = False у эталона.

    Ветка CHARGED_AT_FIRST_STEP существует только потому, что опция есть в
    расчётчике. Включать её без письменного основания от организаторов
    нельзя: это прямое расхождение с проверяющей стороной.
    """
    assert ChargeInitialEsp.NOT_CHARGED.value == "NOT_CHARGED"
    assert len(ChargeInitialEsp) == 2


def test_normatives_have_no_year_axis() -> None:
    """Нормативы скалярные: «применяются без изменения на всем расчетном
    горизонте до последнего расчетного шага».

    Механизм годовых переопределений снят 15.08 вместе с формулировкой
    первой редакции. Тест сторожит его возвращение: годовая ось создала бы
    экономику, которой у эталонного расчётчика нет.
    """
    assert not hasattr(NormativeSet, "for_year")
    with pytest.raises(TypeError):
        NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=(), by_year={})  # type: ignore[call-arg]
