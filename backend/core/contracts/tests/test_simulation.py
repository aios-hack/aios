from dataclasses import replace

import pytest

from backend.core.contracts import (
    FinalNpvArtifact,
    LineItems,
    NpvTable,
    OPM_CONNECTION_SUMMARY_KEYS,
    OPM_WELL_SUMMARY_KEYS,
    SUMMARY_EXPORT_KEYS,
    SubmissionBundle,
    SummarySpec,
)
from backend.core.contracts.simulation import SUBMISSION_BUNDLE_REQUIRED_TEXT_FIELDS


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


SUBMISSION_BUNDLE_VALID: dict[str, object] = {
    "canonical_schedule_hash": "a" * 64,
    "content_hash_submission": "b" * 64,
    "claimed_npv_rub": 1_234_567.5,
    "source_run_id": "run-1",
    "response_hash": "c" * 64,
    "deck_hash": "d" * 64,
    "economics_config_hash": "e" * 64,
    "methodology_version_hash": "f" * 64,
    "constraints_hash": "0" * 64,
    "opm_image": "openporousmedia/opmreleases:latest",
    "git_commit": "1" * 40,
    "created_at": "2026-09-09T12:00:00+00:00",
}


def test_submission_bundle_accepts_valid_payload() -> None:
    bundle = SubmissionBundle(**SUBMISSION_BUNDLE_VALID)

    assert bundle.claimed_npv_rub == 1_234_567.5
    assert bundle.constraints_hash == "0" * 64
    assert bundle.opm_image == "openporousmedia/opmreleases:latest"


@pytest.mark.parametrize("field", SUBMISSION_BUNDLE_REQUIRED_TEXT_FIELDS)
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_submission_bundle_rejects_blank_text_field(field: str, blank: str) -> None:
    payload = dict(SUBMISSION_BUNDLE_VALID)
    payload[field] = blank
    with pytest.raises(ValueError, match=field):
        SubmissionBundle(**payload)


@pytest.mark.parametrize("claimed", [0.0, -0.0, -1.0, -1_000_000.0])
def test_submission_bundle_rejects_non_positive_npv(claimed: float) -> None:
    payload = dict(SUBMISSION_BUNDLE_VALID)
    payload["claimed_npv_rub"] = claimed
    with pytest.raises(ValueError, match="claimed_npv_rub"):
        SubmissionBundle(**payload)


def test_submission_bundle_rejects_nan_npv() -> None:
    payload = dict(SUBMISSION_BUNDLE_VALID)
    payload["claimed_npv_rub"] = float("nan")
    with pytest.raises(ValueError, match="claimed_npv_rub"):
        SubmissionBundle(**payload)
