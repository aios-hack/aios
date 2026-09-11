from __future__ import annotations

from datetime import date

import pytest

from backend.contexts.connectivity.domain.estimator import (
    Batch,
    DriveMatrix,
    LagScan,
    LaggedObservations,
    ProducerObservation,
    best_lag,
    estimate_lambda,
    least_squares,
    realized_drive,
    scan_lag,
    stability_between,
)
from backend.contexts.connectivity.domain.fund import Window
from backend.contexts.connectivity.domain.connectivity import Lambda

INJECTORS = ("I1", "I2", "I3")
PRODUCERS = ("P1", "P2")
WINDOW = Window(start=date(2007, 1, 1), end=date(2009, 1, 1))
BASELINE = {"I1": 30.0, "I2": 30.0, "I3": 30.0}
RIDGE = 1e-6

TRUE_LAMBDA = {
    "P1": (2.0, 0.5, 0.0),
    "P2": (0.0, 1.5, 3.0),
}


def a_drive(scale: float = 6.0, seed: int = 0) -> DriveMatrix:
    signs = (
        (1, -1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, 1, 1),
        (1, -1, 1),
        (-1, 1, 1),
    )
    rotated = signs[seed % len(signs) :] + signs[: seed % len(signs)]
    return DriveMatrix(
        injectors=INJECTORS,
        rows=tuple(tuple(scale * s for s in row) for row in rotated),
    )


def observations_for(
    drive: DriveMatrix, lag_months: int, gain: float = 1.0, noise: float = 0.0
) -> LaggedObservations:
    by_producer = {}
    for producer in PRODUCERS:
        coefficients = TRUE_LAMBDA[producer]
        values = []
        for index, row in enumerate(drive.rows):
            response = sum(
                gain * c * x for c, x in zip(coefficients, row)
            ) + noise * ((index % 3) - 1)
            values.append(500.0 + response)
        by_producer[producer] = ProducerObservation(
            producer=producer,
            cumulative_by_run=tuple(values),
            baseline_cumulative=500.0,
        )
    return LaggedObservations(
        lag_months=lag_months, producers=PRODUCERS, by_producer=by_producer
    )


def test_regression_runs_on_realised_delta_wwir_not_the_planned_levels() -> None:

    actual_by_run = (
        {"I1": 36.0, "I2": 24.0, "I3": 24.0},
        {"I1": 24.0, "I2": 33.0, "I3": 24.0},
    )
    drive = realized_drive(INJECTORS, actual_by_run, BASELINE)
    assert drive.rows[0] == (6.0, -6.0, -6.0)
    assert drive.rows[1] == (-6.0, 3.0, -6.0)
    assert drive.column("I2") == (-6.0, 3.0)


def test_missing_actual_injectivity_is_refused_not_substituted() -> None:
    with pytest.raises(ValueError, match="actual ΔWWIR"):
        realized_drive(INJECTORS, ({"I1": 36.0, "I2": 24.0},), BASELINE)


def test_lag_is_chosen_by_the_maximum_r_squared() -> None:

    drive = a_drive()
    by_lag = {
        0: observations_for(drive, 0, gain=1.0, noise=40.0),
        2: observations_for(drive, 2, gain=1.0, noise=0.0),
        4: observations_for(drive, 4, gain=1.0, noise=60.0),
    }
    scans = scan_lag(drive, by_lag, RIDGE)
    assert [s.lag_months for s in scans] == [0, 2, 4]
    chosen = best_lag(scans)
    assert chosen.lag_months == 2
    assert chosen.r_squared == pytest.approx(1.0, abs=1e-9)


def test_shortest_lag_wins_a_tie() -> None:
    scans = (
        LagScan(lag_months=3, r_squared=0.9),
        LagScan(lag_months=1, r_squared=0.9),
    )
    assert best_lag(scans).lag_months == 1


def test_least_squares_recovers_known_sensitivities() -> None:
    drive = a_drive()
    observations = observations_for(drive, 1)
    fit = least_squares(
        drive.rows, observations.by_producer["P1"].deltas(), RIDGE
    )
    for got, expected in zip(fit.coefficients, TRUE_LAMBDA["P1"]):
        assert got == pytest.approx(expected, abs=1e-4)
    assert fit.r_squared == pytest.approx(1.0, abs=1e-9)


def test_rank_and_condition_number_come_back_with_the_estimate() -> None:

    drive = a_drive()
    diagnostics = drive.diagnostics()
    assert diagnostics.rank == len(INJECTORS)
    assert diagnostics.condition_number < 10.0

    collapsed = DriveMatrix(
        injectors=INJECTORS,
        rows=tuple((row[0], row[0], row[2]) for row in drive.rows),
    )
    degenerate = collapsed.diagnostics()
    assert degenerate.rank < len(INJECTORS)
    assert degenerate.condition_number == float("inf")
    assert degenerate.max_abs_correlation == pytest.approx(1.0)


def test_stability_is_measured_by_two_independent_batches() -> None:

    first = a_drive(seed=0)
    second = a_drive(seed=3)
    batches = (
        Batch(drive=first, observations=observations_for(first, 2)),
        Batch(drive=second, observations=observations_for(second, 2)),
    )
    result = estimate_lambda(
        window=WINDOW,
        producers=PRODUCERS,
        batches=batches,
        lag_months=2,
        amplitude=0.2,
        achievability_ok={well: True for well in INJECTORS},
        ridge=RIDGE,
    )
    assert result.stability == pytest.approx(1.0, abs=1e-6)


def test_a_single_batch_cannot_produce_a_lambda() -> None:
    drive = a_drive()
    single = (Batch(drive=drive, observations=observations_for(drive, 2)),)
    with pytest.raises(ValueError, match="TWO independent"):
        estimate_lambda(
            window=WINDOW,
            producers=PRODUCERS,
            batches=single,
            lag_months=2,
            amplitude=0.2,
            achievability_ok={well: True for well in INJECTORS},
            ridge=RIDGE,
        )


def test_noisy_second_batch_lowers_the_reported_stability() -> None:
    first = a_drive(seed=0)
    second = a_drive(seed=1)
    clean = (
        Batch(drive=first, observations=observations_for(first, 2)),
        Batch(drive=second, observations=observations_for(second, 2)),
    )
    noisy = (
        Batch(drive=first, observations=observations_for(first, 2)),
        Batch(
            drive=second, observations=observations_for(second, 2, gain=1.0, noise=500.0)
        ),
    )
    kwargs = dict(
        window=WINDOW,
        producers=PRODUCERS,
        lag_months=2,
        amplitude=0.2,
        achievability_ok={well: True for well in INJECTORS},
        ridge=RIDGE,
    )
    assert (
        estimate_lambda(batches=noisy, **kwargs).stability
        < estimate_lambda(batches=clean, **kwargs).stability
    )


def test_lambda_carries_its_window_of_applicability() -> None:

    first = a_drive(seed=0)
    second = a_drive(seed=2)
    result = estimate_lambda(
        window=WINDOW,
        producers=PRODUCERS,
        batches=(
            Batch(drive=first, observations=observations_for(first, 3)),
            Batch(drive=second, observations=observations_for(second, 3)),
        ),
        lag_months=3,
        amplitude=0.2,
        achievability_ok={"I1": True, "I2": False, "I3": True},
        ridge=RIDGE,
    )
    assert isinstance(result, Lambda)
    assert result.window_start == WINDOW.start
    assert result.window_end == WINDOW.end
    assert result.producers == PRODUCERS
    assert result.injectors == INJECTORS
    assert result.lag_months == 3
    assert len(result.matrix) == len(PRODUCERS)
    assert len(result.matrix[0]) == len(INJECTORS)
    assert result.achievability_ok["I2"] is False
    assert result.rank == len(INJECTORS)


def test_estimated_matrix_matches_the_planted_sensitivities() -> None:
    first = a_drive(seed=0)
    second = a_drive(seed=4)
    result = estimate_lambda(
        window=WINDOW,
        producers=PRODUCERS,
        batches=(
            Batch(drive=first, observations=observations_for(first, 1)),
            Batch(drive=second, observations=observations_for(second, 1)),
        ),
        lag_months=1,
        amplitude=0.2,
        achievability_ok={well: True for well in INJECTORS},
        ridge=RIDGE,
    )
    for row_index, producer in enumerate(PRODUCERS):
        for col_index, expected in enumerate(TRUE_LAMBDA[producer]):
            assert result.matrix[row_index][col_index] == pytest.approx(
                expected, abs=1e-4
            )


def test_lambda_is_not_constrained_to_sum_to_one() -> None:

    first = a_drive(seed=0)
    second = a_drive(seed=5)
    result = estimate_lambda(
        window=WINDOW,
        producers=PRODUCERS,
        batches=(
            Batch(drive=first, observations=observations_for(first, 1)),
            Batch(drive=second, observations=observations_for(second, 1)),
        ),
        lag_months=1,
        amplitude=0.2,
        achievability_ok={well: True for well in INJECTORS},
        ridge=RIDGE,
    )
    assert sum(result.matrix[1]) > 1.0


def test_batches_on_a_different_fund_are_refused() -> None:
    first = a_drive(seed=0)
    other = DriveMatrix(injectors=("I1", "I2"), rows=((6.0, -6.0), (-6.0, 6.0)))
    observations = observations_for(first, 2)
    with pytest.raises(ValueError, match="different set of injectors"):
        estimate_lambda(
            window=WINDOW,
            producers=PRODUCERS,
            batches=(
                Batch(drive=first, observations=observations),
                Batch(drive=other, observations=observations),
            ),
            lag_months=2,
            amplitude=0.2,
            achievability_ok={well: True for well in INJECTORS},
            ridge=RIDGE,
        )


def test_batches_observed_at_a_different_lag_are_refused() -> None:
    first = a_drive(seed=0)
    second = a_drive(seed=2)
    with pytest.raises(ValueError, match="lag"):
        estimate_lambda(
            window=WINDOW,
            producers=PRODUCERS,
            batches=(
                Batch(drive=first, observations=observations_for(first, 2)),
                Batch(drive=second, observations=observations_for(second, 5)),
            ),
            lag_months=2,
            amplitude=0.2,
            achievability_ok={well: True for well in INJECTORS},
            ridge=RIDGE,
        )


def test_high_r_squared_does_not_mean_separated_effects() -> None:

    rows = ((6.0, 5.9, -6.0), (-6.0, -5.9, -6.0), (-6.0, -5.9, 6.0), (6.0, 5.9, 6.0))
    drive = DriveMatrix(injectors=INJECTORS, rows=rows)
    diagnostics = drive.diagnostics()
    assert diagnostics.rank < len(INJECTORS)
    assert diagnostics.condition_number == float("inf")

    response = [2.0 * r[0] + 0.5 * r[1] + 1.0 * r[2] for r in rows]
    fit = least_squares(rows, response, RIDGE)
    assert fit.r_squared == pytest.approx(1.0, abs=1e-6)
    first, second, _ = fit.coefficients
    assert abs(first - second) < 0.5
    assert first != pytest.approx(2.0, abs=0.1)


def test_regression_on_facts_survives_a_well_pinned_at_the_pressure_limit() -> None:

    healthy = a_drive()
    starved = DriveMatrix(
        injectors=INJECTORS,
        rows=tuple((row[0] / 30.0, row[1], row[2]) for row in healthy.rows),
    )
    reference = estimate_lambda(
        window=WINDOW,
        producers=PRODUCERS,
        batches=(
            Batch(drive=healthy, observations=observations_for(healthy, 2)),
            Batch(drive=healthy, observations=observations_for(healthy, 2)),
        ),
        lag_months=2,
        amplitude=0.2,
        achievability_ok={well: True for well in INJECTORS},
        ridge=RIDGE,
    )
    pinned = estimate_lambda(
        window=WINDOW,
        producers=PRODUCERS,
        batches=(
            Batch(drive=healthy, observations=observations_for(healthy, 2)),
            Batch(drive=starved, observations=observations_for(starved, 2)),
        ),
        lag_months=2,
        amplitude=0.2,
        achievability_ok={"I1": False, "I2": True, "I3": True},
        ridge=RIDGE,
    )

    for row_index, producer in enumerate(PRODUCERS):
        for col_index, expected in enumerate(TRUE_LAMBDA[producer]):
            assert pinned.matrix[row_index][col_index] == pytest.approx(
                expected, abs=1e-3
            )
    assert pinned.condition_number > reference.condition_number
    assert pinned.achievability_ok["I1"] is False


def test_degenerate_batch_pair_has_no_defined_stability() -> None:
    flat = ((0.0, 0.0), (0.0, 0.0))
    with pytest.raises(ValueError, match="stability is undefined"):
        stability_between(flat, flat)
