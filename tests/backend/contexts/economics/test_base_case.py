from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.contracts import (
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
    Policies,
    QuantizationPolicy,
)
from backend.contexts.optimization.application.search_use_case import BASE_NPV
from backend.core.paths import data_root
from backend.domain.economics import (
    ESP_CATALOG_2007,
    MACHINE_ZERO_RUB,
    RUB_PER_MILLION,
    TaxBasis,
    analyze_base_case,
    format_report,
    load_response_artifact,
)
from backend.contexts.economics.domain.decomposition import MACHINE_RELATIVE_TOLERANCE
from backend.domain.schedule import parse_schedule

from conftest import missing_reason, model_z_schedule

BASE_CASE_RESPONSE = (
    data_root() / "base_case" / "response.json"
)

CANONICAL_RUN_ID = "20260816T200926-8b4da543d1ed"
CANONICAL_RESPONSE_HASH = (
    "85f04c6a74ff575d9fe1b25cf3f8a8adcfab998e27b2184036b48d8cd526423f"
)
CANONICAL_NPV_RUB = 11_873_122_324.91
CANONICAL_CONVERSION_COUNT = 0
CANONICAL_STOP_START_COUNT = 41

MODEL_Z_SCHEDULE = model_z_schedule()

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)
POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.NONE,
)

pytestmark = pytest.mark.skipif(
    MODEL_Z_SCHEDULE is None or not BASE_CASE_RESPONSE.is_file(),
    reason=missing_reason(
        "отклик настоящего базового прогона Model_Z "
        f"({BASE_CASE_RESPONSE}) или дек организаторов"
    ),
)


@pytest.fixture(scope="module")
def analysis():
    parsed = parse_schedule(MODEL_Z_SCHEDULE.read_bytes())
    artifact = load_response_artifact(BASE_CASE_RESPONSE)
    return analyze_base_case(
        artifact,
        parsed.dates,
        parsed.t0_deck_date_index,
        NORMATIVES,
        POLICIES,
    )


def test_analysis_runs_on_the_real_base_run_response(analysis) -> None:
    assert analysis.source_run_id
    assert analysis.response_hash
    assert analysis.n_wells > 0
    assert analysis.n_intervals > 0
    assert analysis.n_deck_dates > analysis.n_intervals


def test_artifact_is_the_canonical_base_run(analysis) -> None:
    assert analysis.source_run_id == CANONICAL_RUN_ID
    assert analysis.response_hash == CANONICAL_RESPONSE_HASH


def test_npv_of_canonical_artifact_matches_the_recorded_base(analysis) -> None:
    assert analysis.npv_methodology == pytest.approx(CANONICAL_NPV_RUB, abs=0.01)


def test_search_baseline_constant_equals_the_measured_base(analysis) -> None:
    assert BASE_NPV == CANONICAL_NPV_RUB
    assert analysis.npv_methodology == pytest.approx(BASE_NPV, abs=0.01)


def test_axes_are_derived_from_the_deck_not_hardcoded(analysis) -> None:
    parsed = parse_schedule(MODEL_Z_SCHEDULE.read_bytes())
    assert analysis.n_deck_dates == len(parsed.dates)
    assert analysis.n_intervals == len(parsed.dates) - parsed.t0_deck_date_index - 1
    assert len(analysis.interval_start_dates) == analysis.n_intervals
    assert analysis.interval_start_dates[0] == parsed.dates[parsed.t0_deck_date_index]


def test_npv_by_year_sums_to_npv_methodology(analysis) -> None:
    total = sum(
        analysis.table.by_year[year].discounted_fcf for year in analysis.years
    )
    assert total == pytest.approx(analysis.npv_methodology, abs=MACHINE_ZERO_RUB)


def test_npv_by_month_sums_to_npv_methodology(analysis) -> None:
    total = sum(item.discounted_fcf for item in analysis.table.by_month.values())
    assert total == pytest.approx(analysis.npv_methodology, abs=MACHINE_ZERO_RUB)
    assert len(analysis.table.by_month) == analysis.n_intervals


def test_npv_by_well_sums_to_npv_methodology(analysis) -> None:
    total = sum(item.discounted_fcf for item in analysis.table.by_well.values())
    assert total == pytest.approx(analysis.npv_methodology, abs=MACHINE_ZERO_RUB)
    assert len(analysis.table.by_well) == analysis.n_wells


def test_decomposition_invariants_hold_at_machine_zero(analysis) -> None:
    assert analysis.decomposition.invariants.ok, (
        analysis.decomposition.invariants.format()
    )


def test_interval_series_covers_every_interval(analysis) -> None:
    series = analysis.decomposition.series
    assert len(series.points) == analysis.n_intervals
    assert series.total_discounted_fcf == pytest.approx(
        analysis.npv_methodology, abs=MACHINE_ZERO_RUB, rel=MACHINE_RELATIVE_TOLERANCE
    )
    assert series.points[-1].cumulative_discounted_fcf == pytest.approx(
        analysis.npv_methodology, abs=MACHINE_ZERO_RUB, rel=MACHINE_RELATIVE_TOLERANCE
    )


def test_cost_structure_reconciles_to_fcf(analysis) -> None:
    totals = analysis.totals
    assert totals.ebitda == pytest.approx(
        totals.revenue - totals.deductions - totals.opex_total, abs=1e-3
    )
    assert totals.fcf == pytest.approx(
        totals.ebitda - totals.income_tax - totals.capex_esp, abs=1e-3
    )
    assert totals.revenue > 0.0
    assert totals.opex_total > 0.0


def test_event_tally_uses_factual_response_not_schedule_intent(analysis) -> None:
    assert analysis.response_hash == CANONICAL_RESPONSE_HASH
    events = analysis.events
    assert events.conversion_count == CANONICAL_CONVERSION_COUNT
    assert events.conversion_cost_rub == pytest.approx(0.0)
    assert events.stop_start_count == CANONICAL_STOP_START_COUNT
    assert events.stop_start_cost_rub == pytest.approx(
        events.stop_start_count * NORMATIVES.event_cost_rub
    )



def test_initial_esp_is_not_charged(analysis) -> None:
    events = analysis.events
    assert events.esp_capex_rub == pytest.approx(
        sum(
            cell.capex_esp for cell in analysis.flows
        )
    )
    assert events.esp_swap_count >= 0
    if events.esp_swap_count == 0:
        assert events.esp_capex_rub == pytest.approx(0.0)


def test_per_well_ranking_identifies_loss_making_wells(analysis) -> None:
    ranking = analysis.ranking(TaxBasis.BEFORE_TAX)
    assert len(ranking.contributions) == analysis.n_wells
    values = [item.discounted_fcf for item in ranking.contributions]
    assert values == sorted(values)
    negative = ranking.negative()
    assert all(item.discounted_fcf < 0.0 for item in negative)


def test_before_tax_ranking_sums_without_income_tax(analysis) -> None:
    before = analysis.ranking(TaxBasis.BEFORE_TAX)
    with_tax = analysis.ranking(TaxBasis.WITH_ALLOCATED_TAX)
    assert with_tax.total_discounted_fcf == pytest.approx(
        analysis.npv_methodology, rel=1e-9
    )
    assert before.total_discounted_fcf >= with_tax.total_discounted_fcf


def test_negative_row_rule_excludes_the_terminal_date_only(analysis) -> None:
    if analysis.excluded_row_count:
        assert len(analysis.excluded_dates) >= 1


def test_report_is_printable(analysis) -> None:
    text = format_report(analysis)
    assert "ЧДД по Методике" in text
    assert f"{analysis.npv_methodology / RUB_PER_MILLION:.3f}" in text
