from __future__ import annotations

from pathlib import Path

import pytest

from contracts import DEFAULT_NORMATIVES_2007, NormativeSet

from config import (
    NORMATIVE_FIELDS,
    NormativeSource,
    NormativesLoader,
    normatives_from_mapping,
)
from config.normatives import METHODOLOGY_LOCKED

XLSX = Path(
    "W:/Projects/hacks/aios/docs/models/CHDD_PYTHON/input/Нормативы_ЧДД.xlsx"
)


def test_declared_fields_match_the_contract() -> None:
    assert set(NORMATIVE_FIELDS) == set(DEFAULT_NORMATIVES_2007)


def test_mapping_builds_a_full_scalar_set() -> None:
    normatives = normatives_from_mapping(dict(DEFAULT_NORMATIVES_2007))
    assert normatives.price_oil_rub_per_t == 28_000.0
    assert normatives.wacc == 0.10
    assert normatives.esp_catalog == ()


def test_esp_catalog_is_parsed_when_supplied() -> None:
    raw = dict(DEFAULT_NORMATIVES_2007)
    raw["esp_catalog"] = [
        {
            "nominal": 50.0,
            "interval_low": 25.0,
            "interval_high": 70.0,
            "cost_rub": 1_200_000.0,
        }
    ]
    normatives = normatives_from_mapping(raw)
    assert len(normatives.esp_catalog) == 1
    assert normatives.esp_catalog[0].nominal == 50.0


def test_empty_esp_interval_is_rejected() -> None:
    raw = dict(DEFAULT_NORMATIVES_2007)
    raw["esp_catalog"] = [
        {
            "nominal": 50.0,
            "interval_low": 70.0,
            "interval_high": 25.0,
            "cost_rub": 1_200_000.0,
        }
    ]
    with pytest.raises(ValueError, match="пуст"):
        normatives_from_mapping(raw)


def test_negative_normative_is_rejected() -> None:
    raw = dict(DEFAULT_NORMATIVES_2007)
    raw["opex_oil_rub_per_t"] = -1.0
    with pytest.raises(ValueError, match="отрицательный норматив"):
        normatives_from_mapping(raw)


def test_unknown_normative_is_rejected() -> None:
    raw = dict(DEFAULT_NORMATIVES_2007)
    raw["opex_gas_rub_per_m3"] = 1.0
    with pytest.raises(ValueError, match="незаявленные нормативы"):
        normatives_from_mapping(raw)


def test_methodology_locked_values_are_named() -> None:
    for name in METHODOLOGY_LOCKED:
        assert name in NORMATIVE_FIELDS


def test_source_requires_a_content_hash() -> None:
    with pytest.raises(ValueError, match="без хеша файла"):
        NormativeSource(path=XLSX, content_hash="")


def test_source_rejects_a_truncated_hash() -> None:
    with pytest.raises(ValueError, match="ожидается 64"):
        NormativeSource(path=XLSX, content_hash="abc")


def test_source_delegates_reading_to_the_caller() -> None:
    source = NormativeSource(path=XLSX, content_hash="0" * 64)
    expected = NormativeSet(esp_catalog=(), **DEFAULT_NORMATIVES_2007)
    seen: list[Path] = []

    def loader(path: Path) -> NormativeSet:
        seen.append(path)
        return expected

    assert isinstance(loader, NormativesLoader)
    assert source.load(loader) is expected
    assert seen == [XLSX]


def test_xlsx_is_the_declared_source_of_values() -> None:
    if not XLSX.exists():
        pytest.skip(f"файл нормативов не найден: {XLSX}")
    assert XLSX.suffix == ".xlsx"
