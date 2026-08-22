"""G1: сверка с эталонным расчётчиком на настоящем базовом прогоне Model_Z.

`test_reference_parity.py` доказывает совпадение на учебном примере
организаторов — 2 скважины, 24 интервала. Этот файл — то же самое на
103 скважинах и 224 интервалах реального базового прогона, требуемое
карточкой G1 (`docs/v2/tasks/integration.md`).

Дата до горизонта управления (`deck_step` 0…145, 146 исторических дат)
передаётся эталону с нулевыми `*_Diff`: `ResponseArtifact` не хранит
`raw_diff` для этого диапазона (`IntervalResponse` существует только на
`control_step` 0…223 — README.md §3b, `contracts/response.py`). Это не
искажает сравниваемую экономику: `chdd_model.compute_calculation`
фильтрует строки экономики по `row["DATA"] >= calculation_start_date`
(2007-01-01), а переходы состояния/насоса на границе горизонта детектирует
по ставкам (`WLPR`/`WOMR`/`WWIR`), которые в истории у нас настоящие —
не по `*_Diff`. Из диагностики эталона это занижает только
`sourceCumulativeLiquidKt`/`OilKt`/`InjectionKm3` (сумма по историческим
`*_Diff`, не входит в сравниваемые `LINE_ITEM_FIELDS`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.contracts import ChargeInitialEsp, DEFAULT_NORMATIVES_2007, NormativeSet, Policies, QuantizationPolicy
from backend.domain.economics import ESP_CATALOG_2007, analyze_base_case, load_response_artifact
from backend.domain.economics.base_case import responses_by_well_from_artifact, states_by_well_from_artifact
from backend.domain.economics.reference_parity import build_reference_records, compare_with_reference, run_reference
from backend.domain.schedule import parse_schedule

from conftest import chdd_python_dir, missing_reason, model_z_schedule

CHDD_PYTHON_DIR = chdd_python_dir()
MODEL_Z_SCHEDULE = model_z_schedule()
BASE_CASE_RESPONSE = (
    Path(__file__).resolve().parents[5] / "data" / "base_case" / "response.json"
)

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)
POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.NONE,
)

pytestmark = pytest.mark.skipif(
    CHDD_PYTHON_DIR is None or MODEL_Z_SCHEDULE is None or not BASE_CASE_RESPONSE.is_file(),
    reason=missing_reason(
        "эталонный расчётчик организаторов, дек Model_Z или отклик базового "
        f"прогона ({BASE_CASE_RESPONSE})"
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
    """Приёмка G1: тест падает при расхождении выше машинной точности.

    Расхождение выше нуля здесь — валидный результат карточки, не повод
    ослаблять допуск: `report.raise_if_mismatched()` печатает величину и
    место (до 20 первых статей), не просто «не сошлось».
    """

    report.raise_if_mismatched()


def test_reports_npv_magnitude_for_the_record(report) -> None:
    """Не приёмка сама по себе — фиксирует число рядом с падением/успехом,
    как того просит карточка G1 п.4 «Что сделать»."""

    print(
        f"наш ЧДД={report.npv_ours!r}, эталон={report.npv_reference!r}, "
        f"разница={report.npv_absolute!r}, статей расхождения={len(report.discrepancies)}"
    )
    assert report.npv_ours > 0.0
