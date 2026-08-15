from dataclasses import replace

import pytest

from contracts import (
    FinalNpvArtifact,
    LineItems,
    NpvTable,
    OPM_CONNECTION_SUMMARY_KEYS,
    OPM_WELL_SUMMARY_KEYS,
    SUMMARY_EXPORT_KEYS,
    SummarySpec,
)


def _empty_line() -> LineItems:
    fields = LineItems.__dataclass_fields__
    return LineItems(**{name: (1.0 if name == "df" else 0.0) for name in fields})


def test_summary_spec_separates_export_from_literal_opm_keys() -> None:
    spec = SummarySpec()

    assert spec.export_keys == SUMMARY_EXPORT_KEYS
    assert spec.opm_well_keys == OPM_WELL_SUMMARY_KEYS
    assert spec.opm_connection_keys == OPM_CONNECTION_SUMMARY_KEYS
    assert {"WOMT", "WOMR"}.issubset(spec.export_keys)
    assert {"WOMT", "WOMR"}.isdisjoint(spec.opm_well_keys)
    assert spec.opm_connection_keys == ("COPT", "COPR")
    assert "WMCTL" in spec.opm_well_keys


@pytest.mark.parametrize(
    ("field", "required"),
    [
        ("export_keys", SUMMARY_EXPORT_KEYS),
        ("opm_well_keys", OPM_WELL_SUMMARY_KEYS),
        ("opm_connection_keys", OPM_CONNECTION_SUMMARY_KEYS),
    ],
)
def test_summary_spec_rejects_dropping_or_reordering_keys(
    field: str, required: tuple[str, ...]
) -> None:
    spec = SummarySpec()
    with pytest.raises(ValueError, match=field):
        replace(spec, **{field: required[:-1]})
    with pytest.raises(ValueError, match=field):
        replace(spec, **{field: tuple(reversed(required))})


def test_summary_spec_covers_reference_calculator_columns() -> None:
    """Сторож против отката к прежнему списку из шести ключей.

    WOMR, WTHP и WEFF добавлены 15.08: WOMR и WTHP расчётчик читает,
    WEFF не использует, но требует наличия столбца.
    """
    for key in ("WOMR", "WTHP", "WEFF"):
        assert key in SUMMARY_EXPORT_KEYS


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
