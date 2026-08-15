import pytest

from contracts import FinalNpvArtifact, LineItems, NpvTable, SummarySpec
from contracts.simulation import REQUIRED_SUMMARY_KEYS


def _empty_line() -> LineItems:
    fields = LineItems.__dataclass_fields__
    return LineItems(**{name: (1.0 if name == "df" else 0.0) for name in fields})


def test_summary_spec_requires_mandatory_keys() -> None:
    with pytest.raises(ValueError):
        SummarySpec(keys=("WOMT", "WLPT"))
    SummarySpec(keys=REQUIRED_SUMMARY_KEYS)


def test_summary_spec_rejects_dropping_any_single_key() -> None:
    """Каждый ключ обязателен по отдельности, а не «список примерно такой».

    Состав задан форматом входа эталонного расчётчика ЧДД; выпадение любого
    столбца означает, что выгрузку не примет проверяющая сторона.
    """
    for dropped in REQUIRED_SUMMARY_KEYS:
        keys = tuple(k for k in REQUIRED_SUMMARY_KEYS if k != dropped)
        with pytest.raises(ValueError, match=dropped):
            SummarySpec(keys=keys)


def test_summary_spec_covers_reference_calculator_columns() -> None:
    """Сторож против отката к прежнему списку из шести ключей.

    WOMR, WTHP и WEFF добавлены 15.08: WOMR и WTHP расчётчик читает,
    WEFF не использует, но требует наличия столбца.
    """
    for key in ("WOMR", "WTHP", "WEFF"):
        assert key in REQUIRED_SUMMARY_KEYS


def test_final_npv_artifact_rejects_mismatched_methodology_value() -> None:
    table = NpvTable(by_year={}, by_month={}, by_well={}, npv_methodology=100.0)
    with pytest.raises(ValueError):
        FinalNpvArtifact(
            npv_table=table,
            npv_methodology=200.0,  # разошлось с table.npv_methodology
            source_run_id="run-1",
            source_response_hash="deadbeef",
            economics_config_hash="deadbeef",
            methodology_version_hash="deadbeef",
        )
    FinalNpvArtifact(
        npv_table=table,
        npv_methodology=100.0,
        source_run_id="run-1",
        source_response_hash="deadbeef",
        economics_config_hash="deadbeef",
        methodology_version_hash="deadbeef",
    )
