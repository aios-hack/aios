
from __future__ import annotations

import pytest

from backend.contexts.constraints.domain.config import (
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
    Policies,
    QuantizationPolicy,
)
from backend.contexts.economics.domain.decomposition import MACHINE_ZERO_RUB
from backend.contexts.economics.domain.esp import ESP_CATALOG_2007
from backend.contexts.economics.application.base_case import (
    analyze_base_case,
    load_response_artifact,
)
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.showcase.application.base_artifact import (
    DEFAULT_RESPONSE_PATH,
    REAL_PROVENANCE,
    build_base_artifact,
)

from tests.support.backend.environment import missing_reason, model_z_dir, model_z_schedule

MODEL_Z_DIR = model_z_dir()
MODEL_Z_SCHEDULE = model_z_schedule()

pytestmark = pytest.mark.skipif(
    MODEL_Z_DIR is None or not DEFAULT_RESPONSE_PATH.is_file(),
    reason=missing_reason(
        f"the Model_Z deck or the base run response ({DEFAULT_RESPONSE_PATH})"
    ),
)

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)
POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.NONE,
)


@pytest.fixture(scope="module")
def result():
    return build_base_artifact(NORMATIVES, POLICIES, model_dir=MODEL_Z_DIR)


def test_bundle_is_marked_real_not_synthetic(result) -> None:
    assert result.artifact.schedule.meta.provenance == REAL_PROVENANCE


def test_npv_methodology_matches_independently_recomputed_economics(result) -> None:

    parsed = parse_schedule(MODEL_Z_SCHEDULE.read_bytes())
    artifact = load_response_artifact(DEFAULT_RESPONSE_PATH)
    expected = analyze_base_case(
        artifact, parsed.dates, parsed.t0_deck_date_index, NORMATIVES, POLICIES
    )
    assert result.artifact.npv_table.npv_methodology == pytest.approx(
        expected.npv_methodology, abs=MACHINE_ZERO_RUB
    )


def test_axes_come_from_data_not_hardcoded_literals(result) -> None:
    parsed = parse_schedule(MODEL_Z_SCHEDULE.read_bytes())
    artifact = load_response_artifact(DEFAULT_RESPONSE_PATH)
    n_wells = len({state.well for state in artifact.state_at_date})
    n_intervals = len(parsed.dates) - parsed.t0_deck_date_index - 1

    assert len(result.artifact.schedule.meta.wells) == n_wells
    assert result.artifact.schedule.meta.n_intervals == n_intervals
    assert len(result.artifact.interval_response) == n_wells * n_intervals
