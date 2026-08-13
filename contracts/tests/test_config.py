import pytest

from contracts import DEFAULT_NORMATIVES_2007, NormativeSet, Normatives, PartialNormativeSet


def _base() -> NormativeSet:
    return NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=())


def test_by_year_requires_string_yyyy_keys() -> None:
    with pytest.raises(ValueError):
        Normatives(base=_base(), by_year={2010: PartialNormativeSet()})  # type: ignore[dict-item]
    Normatives(base=_base(), by_year={"2010": PartialNormativeSet()})


def test_for_year_falls_back_to_base() -> None:
    n = Normatives(base=_base())
    assert n.for_year(2015).price_oil_rub_per_t == 28_000.0


def test_for_year_overrides_only_named_fields() -> None:
    n = Normatives(
        base=_base(),
        by_year={"2020": PartialNormativeSet(price_oil_rub_per_t=35_000.0)},
    )
    resolved = n.for_year(2020)
    assert resolved.price_oil_rub_per_t == 35_000.0
    assert resolved.wacc == 0.10  # унаследовано из base, не тронуто override'ом
