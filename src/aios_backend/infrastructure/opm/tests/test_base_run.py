from __future__ import annotations

from math import isnan
from pathlib import Path

import pytest

from aios_backend.infrastructure.opm import MATERIAL_BALANCE_RELATIVE_TOLERANCE, run_base_case
from aios_backend.core.contracts import RunStatus


from conftest import docker_unavailable_reason, missing_reason, model_z_dir

# Через conftest, а не через parents[3]: см. тот же комментарий в test_runner.py.
MODEL_Z = model_z_dir()

DOCKER_REASON = docker_unavailable_reason()

# Проверка Docker — на уровне модуля, а не в функциональной фикстуре: полный
# прогон живёт в module-scoped фикстуре `report`, а её pytest создаёт раньше
# функциональных. Отсутствие демона тогда не давало skip, а падало ошибкой
# фикстуры с `flow завершился кодом 127`.
pytestmark = [
    pytest.mark.skipif(MODEL_Z is None, reason=missing_reason("каталог Model_Z")),
    pytest.mark.skipif(
        DOCKER_REASON is not None,
        reason=f"приёмка задачи 7 требует настоящий OPM Flow; {DOCKER_REASON}",
    ),
]
# Общий с продовым запуском кеш (§4.5): полный физический прогон Model_Z
# занимает реальное время, повторный `pytest` с тем же ключом дека/расписания/
# SummarySpec обязан попасть в кеш, а не гонять симулятор заново.
WORK_ROOT = Path(__file__).resolve().parents[2] / "data" / "base_run"


@pytest.fixture(scope="module")
def report():
    return run_base_case(MODEL_Z, WORK_ROOT)


def test_measures_real_wallclock_time(report) -> None:
    """Ради этого замера задача 7 существует (§7 карточки Андрея)."""

    assert report.run_result.status is RunStatus.OK, report.run_result.message
    assert report.wallclock_seconds > 0.0


def test_material_balance_converges_without_aquifer_correction(report) -> None:
    """§4.7: материальный баланс сходится. В Model_Z нет ни одного AQUCT/

    AQUANCON/AQUFETP (проверено grep по всем `.inc` 16.08) — допуск не несёт
    отдельного аквиферного слагаемого. Баланс берётся агрегатом по всему
    горизонту 0…370, не шаг-к-шагу: `FWIP` (≈2.58·10¹¹ м³) на порядки больше
    помесячного чистого притока воды, шаг-к-шаговая невязка — целиком шум
    округления float32 `UNSMRY`, не физика (докстринг `MaterialBalanceDiagnostics`).
    """

    assert report.material_balance.oil_relative_error < MATERIAL_BALANCE_RELATIVE_TOLERANCE, (
        report.material_balance.oil_relative_error
    )
    assert report.material_balance.water_relative_error < MATERIAL_BALANCE_RELATIVE_TOLERANCE, (
        report.material_balance.water_relative_error
    )


def test_reservoir_pressure_does_not_blow_up(report) -> None:
    """§4.7: пластовое давление не улетает — не отрицательное, не в разы от начального."""

    pressure = report.pressure
    assert pressure.within_bounds, (
        f"FPR ушло за границы: initial={pressure.initial_bar}, "
        f"min={pressure.min_bar}, max={pressure.max_bar}"
    )


def test_watercut_increases_as_a_rule_not_as_hard_oracle(report) -> None:
    """§4.7: обводнённость растёт как правило на длинном горизонте, не помесячно.

    Проверяется тренд (вторая половина истории выше первой), а не строгая
    монотонность шаг-к-шагу — контракт явно запрещает жёсткий oracle
    (исправление 14.08).
    """

    trend = report.watercut_trend
    assert trend.increasing_as_a_rule, (
        f"обводнённость не растёт на длинном горизонте: "
        f"первая половина={trend.first_half_mean:.4f}, вторая={trend.second_half_mean:.4f}"
    )


def test_thirty_injection_conversions_land_on_their_dates(report) -> None:
    """§4.7: 30 переводов под закачку — физическое подтверждение по отклику.

    Не только по расписанию (это уже проверяет `OpmDeckEmitter`, задача 2):
    здесь — что настоящий OPM на дату перевода действительно показывает
    injection_rate > 0 для этой скважины (`docs/context/tools/check_deck_facts.py` §6 —
    источник дат, независимый от `schedule.parse_schedule`).
    """

    assert len(report.conversions) == 30, sorted(c.transition.well for c in report.conversions)
    failed = [c for c in report.conversions if not c.verified]
    assert not failed, [
        (c.transition.well, str(c.transition.event_date), c.injection_rate_at_date) for c in failed
    ]


def test_twenty_two_wells_commissioned_on_their_dates(report) -> None:
    """§4.7: 22 ввода скважин — физическое подтверждение по отклику.

    NOT_COMMISSIONED строго до даты ввода (или скважина — первая дата дека),
    не NOT_COMMISSIONED начиная с неё.
    """

    assert len(report.introductions) == 22, sorted(i.introduction.well for i in report.introductions)
    failed = [i for i in report.introductions if not i.verified]
    assert not failed, [
        (i.introduction.well, i.introduction.deck_date_index, str(i.mode_before), str(i.mode_at))
        for i in failed
    ]


def test_field_series_has_no_missing_or_nan_values(report) -> None:
    """Диагностика бесполезна, если сама содержит дыры — низкий бар, но обязательный."""

    series = report.field_series
    assert len(series.field_pressure_bar) == 371
    for name in (
        "field_pressure_bar",
        "oil_in_place_m3",
        "water_in_place_m3",
        "oil_produced_cum_m3",
        "water_produced_cum_m3",
        "water_injected_cum_m3",
    ):
        values = getattr(series, name)
        assert len(values) == 371, name
        assert not any(isnan(value) for value in values), name
