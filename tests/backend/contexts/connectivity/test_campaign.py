
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import pytest

from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.shared.paths import data_root
from backend.contexts.connectivity.application.connectivity_plan import campaign_plan
from backend.contexts.connectivity.application.campaign import (
    BATCHES_PER_HALF,
    DEFAULT_WINDOW_STEPS,
    CampaignError,
    setup,
)
from backend.contexts.connectivity.domain.doe import Level
from backend.contexts.connectivity.domain.measure import load_lambda, measure, save_lambda

from tests.support.backend.environment import missing_reason, model_z_dir

MODEL_Z = model_z_dir()
BASE_RESPONSE = data_root() / "base_case" / "response.json"

pytestmark = [pytest.mark.skipif(MODEL_Z is None or not BASE_RESPONSE.is_file(), reason=missing_reason(f'Model_Z deck or the baseline run response ({BASE_RESPONSE})')), pytest.mark.slow]


@dataclass(frozen=True, slots=True)
class _Meta:
    scenario_id: str
    from_cache: bool = True


@dataclass(frozen=True, slots=True)
class _Sample:

    schedule: None
    response: ResponseArtifact
    metadata: _Meta


@pytest.fixture(scope="module")
def base_schedule():
    from backend.contexts.schedule.domain.build import build_schedule
    from backend.contexts.schedule.domain.lossless import parse_schedule

    raw = (MODEL_Z / "Model_Z_sch.inc").read_bytes()
    return build_schedule(parse_schedule(raw), raw)


@pytest.fixture(scope="module")
def prepared(base_schedule):
    return setup(MODEL_Z, base_schedule)


@pytest.fixture(scope="module")
def baseline():
    from backend.contexts.economics.application.base_case import load_response_artifact

    return load_response_artifact(BASE_RESPONSE)


def test_plan_width_is_the_active_fund_of_the_window_not_a_constant(prepared) -> None:
    assert len(prepared.fund.injectors) == 27
    assert prepared.window.start.isoformat() == "2007-01-01"
    assert prepared.window.end.isoformat() == "2009-01-01"


def test_four_batches_two_per_half(prepared) -> None:
    assert len(prepared.plans) == 2 * BATCHES_PER_HALF
    seeds = {plan.seed for plan in prepared.plans}
    assert len(seeds) == len(prepared.plans)
    first = prepared.plans[0]
    for other in prepared.plans[1:]:
        assert other.injectors == first.injectors
        assert other.rows != first.rows


def test_too_few_batches_are_refused(base_schedule) -> None:
    with pytest.raises(CampaignError, match="underdetermined"):
        setup(MODEL_Z, base_schedule, batch_seeds=(1, 2))


def test_levels_become_two_sided_factors(prepared) -> None:
    plan = campaign_plan(prepared, seed=1)
    assert len(plan.specs) == sum(len(item.rows) for item in prepared.plans)
    factors = {round(level.factor, 6) for spec in plan.specs for level in spec.levels}
    assert len(factors) == 2
    low, high = sorted(factors)
    assert low < 1.0 < high
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
    assert all(count > len(influence.injectors) for count in report.n_runs_by_batch)


def test_missing_run_is_a_hole_not_a_zero(prepared, baseline) -> None:
    samples = _samples(prepared, baseline)[:-1]
    with pytest.raises(CampaignError, match="is missing"):
        measure(prepared, samples, baseline, n_steps=DEFAULT_WINDOW_STEPS)


def test_measured_lambda_survives_a_round_trip(prepared, baseline, tmp_path) -> None:
    report = measure(
        prepared, _samples(prepared, baseline), baseline, n_steps=DEFAULT_WINDOW_STEPS
    )
    path = save_lambda(
        report,
        tmp_path / "lambda.json",
        measured_at=date(2026, 8, 16),
        source_run_ids=("lambda-b0-0000", "lambda-b1-0000"),
    )
    restored = load_lambda(path)
    assert restored.matrix == report.influence.matrix
    assert restored.injectors == report.influence.injectors
    assert restored.producers == report.influence.producers
    assert restored.window_start == report.influence.window_start
    assert restored.lag_months == report.influence.lag_months
    assert restored.achievability_ok == report.influence.achievability_ok


def test_absent_measurement_raises_instead_of_zero_matrix(tmp_path) -> None:
    with pytest.raises(CampaignError, match="has not run yet"):
        load_lambda(tmp_path / "no-such.json")
