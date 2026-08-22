"""Кампания замера λ: форма плана и проводка выборок через `measure`.

Это **не** приёмка задачи. Приёмка — ненулевая λ, полученная из настоящих
прогонов OPM, и она живёт не в тестах, а в артефакте кампании. Здесь
проверяется ровно то, что можно проверить без симулятора: план строится из
дека, а не из констант; уровни плана переводятся в множители обеих сторон;
идентификаторы сценариев совпадают с теми, по которым `measure` потом
собирает партии. Подложные отклики (правило 4 репозитория) используются
только для проводки формы — ни одно число из них никуда не заявляется.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from backend.core.contracts import ResponseArtifact
from backend.core.paths import data_root
from backend.application.connectivity_plan import campaign_plan
from backend.domain.connectivity.campaign import (
    BATCHES_PER_HALF,
    DEFAULT_WINDOW_STEPS,
    CampaignError,
    setup,
)
from backend.domain.connectivity.doe import Level
from backend.domain.connectivity.measure import load_lambda, measure, save_lambda

from conftest import missing_reason, model_z_dir

MODEL_Z = model_z_dir()
BASE_RESPONSE = data_root() / "base_case" / "response.json"

pytestmark = pytest.mark.skipif(
    MODEL_Z is None or not BASE_RESPONSE.is_file(),
    reason=missing_reason(f"дек Model_Z или отклик базового прогона ({BASE_RESPONSE})"),
)


@dataclass(frozen=True, slots=True)
class _Meta:
    scenario_id: str
    from_cache: bool = True


@dataclass(frozen=True, slots=True)
class _Sample:
    """Пара «расписание → отклик» ровно в той форме, что читает `measure`."""

    schedule: None
    response: ResponseArtifact
    metadata: _Meta


@pytest.fixture(scope="module")
def base_schedule():
    from backend.domain.schedule import build_schedule, parse_schedule

    raw = (MODEL_Z / "Model_Z_sch.inc").read_bytes()
    return build_schedule(parse_schedule(raw), raw)


@pytest.fixture(scope="module")
def prepared(base_schedule):
    return setup(MODEL_Z, base_schedule)


@pytest.fixture(scope="module")
def baseline():
    from backend.domain.economics import load_response_artifact

    return load_response_artifact(BASE_RESPONSE)


def test_plan_width_is_the_active_fund_of_the_window_not_a_constant(prepared) -> None:
    # 27 нагнетательных на 01.01.2007, 41 набирается только к 2022 (§8.1.1):
    # ширина плана — свойство окна, и она обязана прийти из дека.
    assert len(prepared.fund.injectors) == 27
    assert prepared.window.start.isoformat() == "2007-01-01"
    assert prepared.window.end.isoformat() == "2009-01-01"


def test_four_batches_two_per_half(prepared) -> None:
    # Партий четыре, а не две: 27 строк плана против 28 параметров регрессии
    # с интерцептом — одна партия недоопределена. Половина из двух партий
    # даёт 54 наблюдения, устойчивость меряется между половинами.
    assert len(prepared.plans) == 2 * BATCHES_PER_HALF
    seeds = {plan.seed for plan in prepared.plans}
    assert len(seeds) == len(prepared.plans)
    first = prepared.plans[0]
    for other in prepared.plans[1:]:
        assert other.injectors == first.injectors
        assert other.rows != first.rows


def test_too_few_batches_are_refused(base_schedule) -> None:
    with pytest.raises(CampaignError, match="недоопределена"):
        setup(MODEL_Z, base_schedule, batch_seeds=(1, 2))


def test_levels_become_two_sided_factors(prepared) -> None:
    plan = campaign_plan(prepared, seed=1)
    assert len(plan.specs) == sum(len(item.rows) for item in prepared.plans)
    factors = {round(level.factor, 6) for spec in plan.specs for level in spec.levels}
    assert len(factors) == 2
    low, high = sorted(factors)
    assert low < 1.0 < high
    # Множитель симметричен относительно единицы: шаг амплитуды один и тот же
    # в обе стороны, иначе план перестаёт быть сбалансированным.
    assert pytest.approx(high - 1.0, rel=1e-9) == 1.0 - low


def test_every_injector_of_the_window_is_addressed_in_every_run(prepared) -> None:
    plan = campaign_plan(prepared, seed=1)
    expected = set(prepared.fund.injectors)
    for spec in plan.specs:
        assert {level.well for level in spec.levels} == expected
        assert {level.from_step for level in spec.levels} == {0}


def test_scenario_ids_match_what_measure_looks_up(prepared) -> None:
    plan = campaign_plan(prepared, seed=1)
    ids = {spec.scenario_id for spec in plan.specs}
    for batch, doe in enumerate(prepared.plans):
        for row in doe.rows:
            assert f"lambda-b{batch}-{row.run_index:04d}" in ids


def _samples(prepared, baseline) -> list[_Sample]:
    """Подложные отклики: приёмистость двигается по уровню строки плана.

    Форма, не физика. Добыча двигается детерминированно вместе с суммой
    уровней строки — без разброса отклика регрессия вырождается и партии
    нечем сравнивать. Ни одно число отсюда никуда не заявляется.
    """

    injectors = set(prepared.fund.injectors)
    samples: list[_Sample] = []
    for batch, doe in enumerate(prepared.plans):
        for row in doe.rows:
            signs = {
                well: (1.0 if level is Level.HIGH else -1.0)
                for well, level in row.levels.items()
            }
            states = tuple(
                replace(
                    state,
                    injection_rate=state.injection_rate
                    * (1.0 + 0.33 * signs.get(state.well, 0.0)),
                )
                if state.well in injectors
                else state
                for state in baseline.state_at_date
            )
            drive = sum(signs.values()) / len(signs)
            intervals = tuple(
                replace(
                    item,
                    liquid_volume_delta=item.liquid_volume_delta
                    * (1.0 + 0.01 * drive * (1 + row.run_index % 3)),
                )
                for item in baseline.interval_response
            )
            samples.append(
                _Sample(
                    schedule=None,
                    response=ResponseArtifact(
                        source_run_id=f"synthetic-{batch}-{row.run_index}",
                        response_hash="0" * 64,
                        state_at_date=states,
                        interval_response=intervals,
                    ),
                    metadata=_Meta(f"lambda-b{batch}-{row.run_index:04d}"),
                )
            )
    return samples


def test_measure_walks_the_whole_chain_on_synthetic_responses(prepared, baseline) -> None:
    report = measure(
        prepared, _samples(prepared, baseline), baseline, n_steps=DEFAULT_WINDOW_STEPS
    )
    influence = report.influence
    assert influence.injectors == prepared.fund.injectors
    assert influence.producers == prepared.fund.producers
    assert len(influence.matrix) == len(influence.producers)
    assert all(len(row) == len(influence.injectors) for row in influence.matrix)
    assert influence.window_start == prepared.window.start
    assert influence.window_end == prepared.window.end
    assert len(report.n_runs_by_batch) == 2
    # Половина обязана быть переопределённой, иначе R² единица на любом лаге.
    assert all(count > len(influence.injectors) for count in report.n_runs_by_batch)


def test_missing_run_is_a_hole_not_a_zero(prepared, baseline) -> None:
    # Дозаполнять выпавшую строку плана нулём запрещено: это выдуманное
    # воздействие, а не пропуск. `measure` обязан упасть.
    samples = _samples(prepared, baseline)[:-1]
    with pytest.raises(CampaignError, match="нет прогона"):
        measure(prepared, samples, baseline, n_steps=DEFAULT_WINDOW_STEPS)


def test_measured_lambda_survives_a_round_trip(prepared, baseline, tmp_path) -> None:
    report = measure(
        prepared, _samples(prepared, baseline), baseline, n_steps=DEFAULT_WINDOW_STEPS
    )
    path = save_lambda(report, tmp_path / "lambda.json")
    restored = load_lambda(path)
    assert restored.matrix == report.influence.matrix
    assert restored.injectors == report.influence.injectors
    assert restored.producers == report.influence.producers
    assert restored.window_start == report.influence.window_start
    assert restored.lag_months == report.influence.lag_months
    assert restored.achievability_ok == report.influence.achievability_ok


def test_absent_measurement_raises_instead_of_zero_matrix(tmp_path) -> None:
    # Нулевая матрица правильной формы неотличима от измерения глазами —
    # правило 3: несчитанное не подменяется правдоподобным.
    with pytest.raises(CampaignError, match="ещё не отрабатывала"):
        load_lambda(tmp_path / "нет-такого.json")
