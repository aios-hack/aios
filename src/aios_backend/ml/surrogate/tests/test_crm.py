from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from aios_backend.core.contracts import IntervalResponse, N_INTERVALS, RunResult, RunStatus
from aios_backend.domain.schedule import load_schedule
from aios_backend.ml.surrogate.crm import (
    BaselineComparison,
    CrmBaseline,
    CrmError,
    CrmSplit,
    compare_to_baseline,
    predict_liquid,
    spearman,
)

from conftest import base_run_dir, base_run_output_dir, missing_reason


def synthetic_response(
    n_intervals: int = 40,
    producers: tuple[str, ...] = ("P1", "P2"),
    injectors: tuple[str, ...] = ("I1", "I2"),
) -> tuple[IntervalResponse, ...]:
    rows: list[IntervalResponse] = []
    for k in range(n_intervals):
        for index, well in enumerate(injectors):
            volume = 1000.0 + 100.0 * index + 50.0 * ((k * (index + 3)) % 7)
            rows.append(
                IntervalResponse(
                    control_step=k,
                    well=well,
                    oil_mass_delta=0.0,
                    liquid_volume_delta=0.0,
                    injection_volume_delta=volume,
                )
            )
        for index, well in enumerate(producers):
            liquid = 300.0 + 20.0 * index + 30.0 * ((k * (index + 2)) % 5) + 0.5 * k
            rows.append(
                IntervalResponse(
                    control_step=k,
                    well=well,
                    oil_mass_delta=liquid * 0.4,
                    liquid_volume_delta=liquid,
                    injection_volume_delta=0.0,
                )
            )
    return tuple(rows)


def test_split_rejects_degenerate_holdout() -> None:
    with pytest.raises(CrmError):
        CrmSplit(train_intervals=40, n_intervals=40)
    with pytest.raises(CrmError):
        CrmSplit(train_intervals=0, n_intervals=40)


def test_split_exposes_disjoint_covering_ranges() -> None:
    split = CrmSplit(train_intervals=30, n_intervals=40)
    assert split.holdout_intervals == 10
    assert set(split.train_steps).isdisjoint(split.holdout_steps)
    assert set(split.train_steps) | set(split.holdout_steps) == set(range(40))


def test_spearman_is_invariant_to_monotone_rescaling() -> None:
    actual = [1.0, 5.0, 2.0, 8.0, 3.0]
    predicted = [10.0, 50.0, 20.0, 80.0, 30.0]
    assert spearman(actual, predicted) == pytest.approx(1.0)
    assert spearman(actual, [-v for v in predicted]) == pytest.approx(-1.0)


def test_spearman_handles_ties_through_average_rank() -> None:
    assert spearman([1.0, 1.0, 2.0], [5.0, 5.0, 9.0]) == pytest.approx(1.0)


def test_fit_produces_contract_shaped_axes() -> None:
    evaluation = CrmBaseline().fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    model = evaluation.model
    assert model.producers == ("P1", "P2")
    assert model.injectors == ("I1", "I2")
    assert len(model.allocation) == len(model.producers)
    assert all(len(row) == len(model.injectors) for row in model.allocation)
    assert len(model.base_liquid) == len(model.producers)


def test_allocation_coefficients_are_non_negative() -> None:
    evaluation = CrmBaseline().fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    assert all(value >= 0.0 for row in evaluation.model.allocation for value in row)


def test_material_balance_holds_per_injector_column() -> None:
    evaluation = CrmBaseline().fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    assert evaluation.model.material_balance_enforced
    assert evaluation.model.max_injector_allocation_sum() <= 1.0 + 1e-9


def test_material_balance_can_be_disabled_and_then_may_be_violated() -> None:
    unconstrained = CrmBaseline(enforce_material_balance=False).fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    assert not unconstrained.model.material_balance_enforced


def test_metrics_are_measured_on_the_holdout_not_the_training_part() -> None:
    evaluation = CrmBaseline().fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    assert evaluation.holdout.n_points == 10 * len(evaluation.model.producers)
    assert evaluation.train.n_points == 30 * len(evaluation.model.producers)
    assert evaluation.holdout.n_points != evaluation.train.n_points


def test_fit_rejects_response_without_a_fully_active_producer() -> None:
    rows = [
        row
        for row in synthetic_response(n_intervals=40)
        if not (row.well == "P1" and row.control_step == 7)
    ]
    rows.append(
        IntervalResponse(
            control_step=7,
            well="P1",
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=0.0,
        )
    )
    rows = [row for row in rows if row.well != "P2"]
    with pytest.raises(CrmError):
        CrmBaseline().fit(tuple(rows), train_intervals=30, n_intervals=40)


def test_fit_rejects_duplicate_rows() -> None:
    rows = list(synthetic_response(n_intervals=40))
    rows.append(rows[0])
    with pytest.raises(CrmError):
        CrmBaseline().fit(tuple(rows), train_intervals=30, n_intervals=40)


def test_predict_liquid_reproduces_the_fitted_training_response() -> None:
    response = synthetic_response(n_intervals=40)
    evaluation = CrmBaseline().fit(response, train_intervals=30, n_intervals=40)
    injection = {
        well: [
            row.injection_volume_delta
            for row in sorted(
                (r for r in response if r.well == well), key=lambda r: r.control_step
            )
        ]
        for well in evaluation.model.injectors
    }
    predicted = predict_liquid(evaluation.model, injection, 40)
    assert set(predicted) == set(evaluation.model.producers)
    assert all(len(series) == 40 for series in predicted.values())


def test_predict_liquid_requires_every_injector() -> None:
    evaluation = CrmBaseline().fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    with pytest.raises(CrmError):
        predict_liquid(evaluation.model, {"I1": [0.0] * 40}, 40)


def test_zero_injection_prediction_falls_back_to_the_base_level() -> None:
    evaluation = CrmBaseline().fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    model = evaluation.model
    predicted = predict_liquid(
        model, {well: [0.0] * 40 for well in model.injectors}, 40
    )
    for index, producer in enumerate(model.producers):
        assert predicted[producer][-1] == pytest.approx(model.base_liquid[index])


def test_compare_to_baseline_requires_the_same_sample() -> None:
    evaluation = CrmBaseline().fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    other = CrmBaseline().fit(
        synthetic_response(), train_intervals=20, n_intervals=40
    )
    with pytest.raises(CrmError):
        compare_to_baseline(evaluation.holdout, other.holdout)


def test_compare_to_baseline_reports_rank_correlation_gain() -> None:
    evaluation = CrmBaseline().fit(
        synthetic_response(), train_intervals=30, n_intervals=40
    )
    identical = compare_to_baseline(evaluation.holdout, evaluation.holdout)
    assert isinstance(identical, BaselineComparison)
    assert identical.rank_correlation_gain == pytest.approx(0.0)
    assert not identical.beats_baseline


def _load_real_response():
    output = base_run_output_dir()
    if output is None:
        return None
    deck = base_run_dir() / "deck"
    if not (deck / "Model_Z_sch.inc").is_file():
        return None
    from aios_backend.infrastructure.opm import ResponseLoader, build_summary_plan, load_density_by_pvtnum

    schedule = load_schedule(deck / "Model_Z_sch.inc")
    plan = build_summary_plan(deck, sorted(schedule.meta.wells))
    density = load_density_by_pvtnum(deck)
    run_result = RunResult(
        run_id=output.parent.name,
        status=RunStatus.OK,
        deck_hash="",
        canonical_schedule_hash="",
        summary_hash="",
        artifacts=tuple(str(path) for path in output.iterdir()),
        wallclock_seconds=0.0,
        message="",
    )
    return ResponseLoader().load(run_result, plan, schedule, density)


REAL_RESPONSE = _load_real_response()

real_response = pytest.mark.skipif(
    REAL_RESPONSE is None,
    reason=missing_reason("сохранённый отклик настоящего прогона OPM"),
)

REAL_TRAIN_INTERVALS = 168


@real_response
def test_real_response_fits_on_the_contract_axis() -> None:
    evaluation = CrmBaseline().fit(
        REAL_RESPONSE.interval_response, train_intervals=REAL_TRAIN_INTERVALS
    )
    model = evaluation.model
    assert model.split.n_intervals == N_INTERVALS
    assert model.split.holdout_intervals == N_INTERVALS - REAL_TRAIN_INTERVALS
    assert len(model.producers) > 0
    assert len(model.injectors) > 0
    assert evaluation.holdout.n_points == (
        model.split.holdout_intervals * len(model.producers)
    )


@real_response
def test_real_response_material_balance_is_not_violated() -> None:
    evaluation = CrmBaseline().fit(
        REAL_RESPONSE.interval_response, train_intervals=REAL_TRAIN_INTERVALS
    )
    assert evaluation.model.max_injector_allocation_sum() <= 1.0 + 1e-9
    assert all(
        value >= 0.0 for row in evaluation.model.allocation for value in row
    )


@real_response
def test_real_response_holdout_quality_is_a_usable_threshold() -> None:
    evaluation = CrmBaseline().fit(
        REAL_RESPONSE.interval_response, train_intervals=REAL_TRAIN_INTERVALS
    )
    assert evaluation.holdout.r2 > 0.5
    assert evaluation.holdout.spearman_rank_correlation > 0.5


@real_response
def test_real_response_holdout_is_not_inflated_by_memorization() -> None:
    evaluation = CrmBaseline().fit(
        REAL_RESPONSE.interval_response, train_intervals=REAL_TRAIN_INTERVALS
    )
    assert evaluation.generalization_gap < 0.1


@real_response
def test_material_balance_constraint_is_what_makes_the_fit_generalize() -> None:
    constrained = CrmBaseline().fit(
        REAL_RESPONSE.interval_response, train_intervals=REAL_TRAIN_INTERVALS
    )
    assert constrained.model.max_injector_allocation_sum() <= 1.0 + 1e-9
    unconstrained = CrmBaseline(enforce_material_balance=False).fit(
        REAL_RESPONSE.interval_response, train_intervals=REAL_TRAIN_INTERVALS
    )
    assert unconstrained.model.max_injector_allocation_sum() > 1.0
    assert constrained.holdout.r2 > 0.0


@real_response
def test_negative_allocation_would_destroy_generalization() -> None:
    baseline = CrmBaseline()
    evaluation = baseline.fit(
        REAL_RESPONSE.interval_response, train_intervals=REAL_TRAIN_INTERVALS
    )
    assert evaluation.holdout.r2 > 0.0
    assert evaluation.holdout.mae > 0.0
    assert evaluation.holdout.median_relative_error < 1.0
