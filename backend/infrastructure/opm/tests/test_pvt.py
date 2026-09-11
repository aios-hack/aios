from __future__ import annotations

from pathlib import Path

import pytest

from backend.contexts.reservoir.infrastructure.pvt import PvtError, PvtTables, load_pvt, parse_pvt

from conftest import model_z_dir

_SYNTHETIC = """
-- заголовок из тНавигатора
PVTO
-- gor      pressure  fvf     viscosity
   0.005    100       1.0100  34.0
            200       1.0000  35.0
            300       0.9900  36.0 /
   0.010    200       1.0300  30.0
            300       1.0200  31.0 /
/
   0.007    100       1.2000  20.0
            300       1.1000  22.0 /
/


PVTW
-- pref fvf compressibility viscosity viscosibility
   100  1   0.0             1.6       /
   100  2*1.5               1.6       /


DENSITY
   900 1000 1.0 /
   910 1010 1.1 /
"""


@pytest.fixture(scope="module")
def deck_pvt() -> PvtTables:
    model_dir = model_z_dir()
    if model_dir is None:
        pytest.skip("дек Model_Z недоступен")
    return load_pvt(model_dir)


def test_deck_known_values(deck_pvt: PvtTables) -> None:
    assert deck_pvt.region_count == 2
    region = deck_pvt.region(1)
    assert region.water_formation_volume_factor(123.0) == pytest.approx(1.0, abs=1e-9)
    assert region.oil_formation_volume_factor(123.0) == pytest.approx(0.99685, abs=1e-4)
    assert region.oil.saturation_pressure_bar == pytest.approx(1.1325, abs=1e-4)
    assert region.oil.saturated_rs == pytest.approx(0.00540, abs=1e-5)
    assert region.oil.viscosity_at(1.1325) == pytest.approx(34.2, abs=0.1)
    assert region.density.oil_kg_per_m3 == pytest.approx(913.0765883224138)


def test_deck_bo_at_saturation_matches_first_row(deck_pvt: PvtTables) -> None:
    region = deck_pvt.region(1)
    assert region.oil_formation_volume_factor(1.1325) == pytest.approx(
        1.0014479631678546, abs=1e-12
    )


def test_deck_regions_differ(deck_pvt: PvtTables) -> None:
    first = deck_pvt.region(1)
    second = deck_pvt.region(2)
    assert first.density.oil_kg_per_m3 != second.density.oil_kg_per_m3
    assert first.oil.saturated_rs != second.oil.saturated_rs
    assert first.oil.viscosity_at(1.1325) != second.oil.viscosity_at(1.1325)
    assert second.water.reference_pressure_bar == pytest.approx(125.0)


def test_deck_pressure_outside_table_raises(deck_pvt: PvtTables) -> None:
    region = deck_pvt.region(1)
    with pytest.raises(PvtError, match="вне таблицы"):
        region.oil_formation_volume_factor(0.5)
    with pytest.raises(PvtError, match="вне таблицы"):
        region.oil_formation_volume_factor(1000.0)


def test_deck_missing_region_raises(deck_pvt: PvtTables) -> None:
    with pytest.raises(PvtError, match="PVT-регион 5 отсутствует"):
        deck_pvt.region(5)


def test_synthetic_comments_and_terminators() -> None:
    tables = parse_pvt(_SYNTHETIC, "synthetic")
    assert tables.region_count == 2
    first = tables.region(1)
    assert first.oil.branches[0].pressure_bar == (100.0, 200.0, 300.0)
    assert first.oil.branches[0].viscosity_cp == (34.0, 35.0, 36.0)
    assert len(first.oil.branches) == 2
    assert tables.region(2).oil.branches[0].rs == pytest.approx(0.007)


def test_synthetic_linear_interpolation() -> None:
    tables = parse_pvt(_SYNTHETIC, "synthetic")
    region = tables.region(1)
    assert region.oil_formation_volume_factor(150.0) == pytest.approx(1.005)
    assert region.oil_formation_volume_factor(250.0) == pytest.approx(0.995)
    assert region.oil_formation_volume_factor(200.0) == pytest.approx(1.0)


def test_synthetic_repeat_counts_expand() -> None:
    tables = parse_pvt(_SYNTHETIC, "synthetic")
    water = tables.region(2).water
    assert water.formation_volume_factor_ref == pytest.approx(1.5)
    assert water.compressibility_per_bar == pytest.approx(1.5)
    assert water.viscosity_cp == pytest.approx(1.6)


def test_repeat_count_zero_rejected() -> None:
    text = _SYNTHETIC.replace("2*1.5", "0*1.5")
    with pytest.raises(PvtError, match="больше нуля"):
        parse_pvt(text, "synthetic")


def test_repeat_without_value_rejected() -> None:
    text = _SYNTHETIC.replace("2*1.5", "2* 1.5 1.5")
    with pytest.raises(PvtError, match="не указано повторяемое значение"):
        parse_pvt(text, "synthetic")


def test_water_incompressible_is_flat() -> None:
    tables = parse_pvt(_SYNTHETIC, "synthetic")
    water = tables.region(1).water
    assert water.formation_volume_factor_at(1.0) == pytest.approx(1.0)
    assert water.formation_volume_factor_at(400.0) == pytest.approx(1.0)


def test_water_compressible_shrinks_with_pressure() -> None:
    tables = load_pvt_from_text_with_compressible_water()
    water = tables.region(1).water
    assert water.formation_volume_factor_at(200.0) < water.formation_volume_factor_at(
        100.0
    )


def load_pvt_from_text_with_compressible_water() -> PvtTables:
    text = _SYNTHETIC.replace("   100  1   0.0", "   100  1   0.00005")
    return parse_pvt(text, "synthetic")


_WITHOUT_PVTO = """
PVTW
   100  1   0.0   1.6 /
DENSITY
   900 1000 1.0 /
"""

_WITHOUT_PVTW = """
PVTO
   0.005    100       1.0100  34.0
            200       1.0000  35.0 /
/
DENSITY
   900 1000 1.0 /
"""

_WITHOUT_DENSITY = """
PVTO
   0.005    100       1.0100  34.0
            200       1.0000  35.0 /
/
PVTW
   100  1   0.0   1.6 /
"""


@pytest.mark.parametrize(
    ("keyword", "text"),
    [
        ("PVTO", _WITHOUT_PVTO),
        ("PVTW", _WITHOUT_PVTW),
        ("DENSITY", _WITHOUT_DENSITY),
    ],
)
def test_missing_keyword_raises(keyword: str, text: str) -> None:
    with pytest.raises(PvtError, match=f"{keyword} отсутствует"):
        parse_pvt(text, "synthetic")


def test_empty_keyword_block_raises() -> None:
    text = "PVTO\nPVTW\n 100 1 0.0 1.6 /\nDENSITY\n 900 1000 1.0 /\n"
    with pytest.raises(PvtError, match="не содержит записей"):
        parse_pvt(text, "synthetic")


def test_region_count_mismatch_raises() -> None:
    text = _SYNTHETIC.replace("   100  2*1.5               1.6       /\n", "")
    with pytest.raises(PvtError, match="расходится между ключевыми словами"):
        parse_pvt(text, "synthetic")


def test_unclosed_block_raises() -> None:
    text = _SYNTHETIC.replace("   910 1010 1.1 /", "   910 1010 1.1")
    with pytest.raises(PvtError, match="не закрыт"):
        parse_pvt(text, "synthetic")


def test_non_numeric_token_raises() -> None:
    text = _SYNTHETIC.replace("   900 1000 1.0 /", "   900 abc 1.0 /")
    with pytest.raises(PvtError, match="не является числом"):
        parse_pvt(text, "synthetic")


def test_density_wrong_field_count_raises() -> None:
    text = _SYNTHETIC.replace("   900 1000 1.0 /", "   900 1000 /")
    with pytest.raises(PvtError, match="DENSITY: запись должна содержать три числа"):
        parse_pvt(text, "synthetic")


def test_load_pvt_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="файл свойств дека не найден"):
        load_pvt(tmp_path)


def test_gas_oil_ratio_interpolates_over_branches() -> None:
    tables = parse_pvt(_SYNTHETIC, "synthetic")
    oil = tables.region(1).oil
    assert oil.gas_oil_ratio_at(100.0) == pytest.approx(0.005)
    assert oil.gas_oil_ratio_at(200.0) == pytest.approx(0.010)
    assert oil.gas_oil_ratio_at(150.0) == pytest.approx(0.0075)
