import pytest

from contracts import FinalNpvArtifact, LineItems, NpvTable, SummarySpec


def _empty_line() -> LineItems:
    return LineItems(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1.0, 0)


def test_summary_spec_requires_mandatory_keys() -> None:
    with pytest.raises(ValueError):
        SummarySpec(keys=("WOMT", "WLPT"))
    SummarySpec(keys=("WOMT", "WLPT", "WWIT", "WLPR", "WWIR", "WBHP"))


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
