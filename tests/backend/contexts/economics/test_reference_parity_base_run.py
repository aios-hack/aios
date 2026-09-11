
from __future__ import annotations

from pathlib import Path

import pytest

from backend.contexts.constraints.domain.config import (
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
    Policies,
    QuantizationPolicy,
)
from backend.shared.paths import data_root
from backend.contexts.economics.domain.esp import ESP_CATALOG_2007
from backend.contexts.economics.application.base_case import (
    analyze_base_case,
    load_response_artifact,
)
from backend.contexts.economics.application.base_case import (
    responses_by_well_from_artifact,
    states_by_well_from_artifact,
)
from backend.contexts.economics.application.reference_parity import (
    build_reference_records,
    compare_with_reference,
    run_reference,
)
from backend.contexts.schedule.domain.lossless import parse_schedule

from tests.support.backend.environment import chdd_python_dir, missing_reason, model_z_schedule

CHDD_PYTHON_DIR = chdd_python_dir()
MODEL_Z_SCHEDULE = model_z_schedule()
BASE_CASE_RESPONSE = (
    data_root() / "base_case" / "response.json"
)

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)
POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.NONE,
)

pytestmark = pytest.mark.skipif(
    CHDD_PYTHON_DIR is None or MODEL_Z_SCHEDULE is None or not BASE_CASE_RESPONSE.is_file(),
    reason=missing_reason(
        "the organizers' reference calculator, the Model_Z deck or the base run "
        f"response ({BASE_CASE_RESPONSE})"
    ),
)


@pytest.fixture(scope="module")
def report():
    parsed = parse_schedule(MODEL_Z_SCHEDULE.read_bytes())
    artifact = load_response_artifact(BASE_CASE_RESPONSE)
    analysis = analyze_base_case(
        artifact, parsed.dates, parsed.t0_deck_date_index, NORMATIVES, POLICIES
    )
    records = build_reference_records(
        states_by_well_from_artifact(artifact),
        responses_by_well_from_artifact(artifact),
        analysis.interval_start_dates,
    )
    reference_result = run_reference(
        CHDD_PYTHON_DIR,
        records,
        NORMATIVES,
        POLICIES,
        start_year=analysis.interval_start_dates[0].year,
    )
    return compare_with_reference(analysis.table, reference_result, analysis.interval_start_dates)


def test_matches_reference_at_machine_precision_on_103_wells_224_intervals(report) -> None:

    report.raise_if_mismatched()


def test_reports_npv_magnitude_for_the_record(report) -> None:

    print(
        f"our NPV={report.npv_ours!r}, reference={report.npv_reference!r}, "
        f"difference={report.npv_absolute!r}, diverging items={len(report.discrepancies)}"
    )
    assert report.npv_ours > 0.0
