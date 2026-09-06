"""Приёмка гейта 6: интервал ЧДД с подтверждённым покрытием."""

from __future__ import annotations

import pytest

from surrogate.npv_interval import (
    MIN_CALIBRATION_SCENARIOS,
    ConformalNpvInterval,
    NpvIntervalError,
    lower_bounds,
)


def _calibration(n: int = 100, step: float = 1e6) -> tuple[list[float], list[float]]:
    """Остатки 0, ±step, ±2·step… — квантиль считается точно и проверяемо."""

    actual = [float(i) * step for i in range(n)]
    predicted = [value - step * (index % 5) for index, value in enumerate(actual)]
    return actual, predicted


def _fit(level: float = 0.9, n: int = 100) -> ConformalNpvInterval:
    actual, predicted = _calibration(n)
    return ConformalNpvInterval.fit(
        actual,
        predicted,
        level=level,
        population="train-holdout",
        population_used_in_training=False,
    )


def test_half_width_is_the_conformal_order_statistic() -> None:
    """Полуширина — ⌈(n+1)·level⌉-я по величине из n остатков, не среднее."""

    actual = [0.0] * 20
    predicted = [-float(i) for i in range(20)]  # остатки 0…19
    interval = ConformalNpvInterval.fit(
        actual,
        predicted,
        level=0.9,
        population="train-holdout",
        population_used_in_training=False,
    )

    # ⌈21 × 0.9⌉ = 19 → девятнадцатый по возрастанию остаток, то есть 18.0
    assert interval.half_width_rub == pytest.approx(18.0)


def test_interval_is_symmetric_around_the_prediction() -> None:
    interval = _fit()
    low, high = interval.interval(11_800_000_000.0)

    assert high - 11_800_000_000.0 == pytest.approx(interval.half_width_rub)
    assert 11_800_000_000.0 - low == pytest.approx(interval.half_width_rub)


def test_lower_bound_is_what_the_loop_ranks_by() -> None:
    interval = _fit()
    bounds = lower_bounds(interval, (10.0e9, 12.0e9, 11.0e9))

    assert bounds == tuple(
        value - interval.half_width_rub for value in (10.0e9, 12.0e9, 11.0e9)
    )
    # Порядок не меняется: сдвиг общий, а не подгонка под кандидата.
    assert sorted(bounds) == [bounds[0], bounds[2], bounds[1]]


# --- главная защита: выборка, участвовавшая в обучении ------------------------


def test_refuses_a_population_that_took_part_in_training() -> None:
    """Замер: калибровка по validation дала 59% покрытия при заявленных 80%."""

    actual, predicted = _calibration()
    with pytest.raises(NpvIntervalError, match="участвовала в обучении"):
        ConformalNpvInterval.fit(
            actual,
            predicted,
            level=0.8,
            population="validation",
            population_used_in_training=True,
        )


def test_training_flag_has_no_default_and_must_be_stated() -> None:
    """Происхождение выборки нельзя забыть: ошибка не видна в числах."""

    actual, predicted = _calibration()
    with pytest.raises(TypeError):
        ConformalNpvInterval.fit(  # type: ignore[call-arg]
            actual, predicted, level=0.9, population="train-holdout"
        )


def test_coverage_cannot_be_measured_on_the_calibration_population() -> None:
    interval = _fit()
    actual, predicted = _calibration()
    with pytest.raises(NpvIntervalError, match="той же выборке"):
        interval.check_coverage(actual, predicted, population="train-holdout")


# --- измеренное покрытие ------------------------------------------------------


def test_coverage_counts_facts_inside_the_interval() -> None:
    interval = ConformalNpvInterval(
        level=0.9,
        half_width_rub=10.0,
        n_calibration=100,
        calibration_population="train-holdout",
    )
    check = interval.check_coverage(
        [0.0, 0.0, 0.0, 0.0],
        [5.0, -9.0, 11.0, 100.0],
        population="test",
    )

    assert check.n_scenarios == 4
    assert check.covered == 2
    assert check.coverage == pytest.approx(0.5)
    assert check.shortfall == pytest.approx(0.4)


def test_shortfall_is_negative_when_coverage_exceeds_the_claim() -> None:
    interval = ConformalNpvInterval(
        level=0.5,
        half_width_rub=1_000.0,
        n_calibration=50,
        calibration_population="train-holdout",
    )
    check = interval.check_coverage([0.0, 0.0], [1.0, 2.0], population="test")

    assert check.coverage == pytest.approx(1.0)
    assert check.shortfall < 0.0


def test_report_carries_measured_coverage_next_to_the_claim() -> None:
    interval = _fit()
    check = interval.check_coverage([0.0], [0.0], population="test")
    payload = interval.as_dict((check,))

    assert payload["format"] == "aios.surrogate-npv-conformal-interval.v1"
    assert payload["level"] == 0.9
    assert payload["measured_coverage"][0]["population"] == "test"
    assert payload["calibration_population"] == "train-holdout"


# --- отказы -------------------------------------------------------------------


def test_refuses_a_calibration_sample_too_small_for_the_guarantee() -> None:
    actual, predicted = _calibration(n=MIN_CALIBRATION_SCENARIOS - 1)
    with pytest.raises(NpvIntervalError, match="не даёт гарантии"):
        ConformalNpvInterval.fit(
            actual,
            predicted,
            level=0.95,
            population="train-holdout",
            population_used_in_training=False,
        )


def test_refuses_an_unnamed_calibration_population() -> None:
    with pytest.raises(NpvIntervalError, match="обязана быть названа"):
        ConformalNpvInterval(
            level=0.9,
            half_width_rub=1.0,
            n_calibration=100,
            calibration_population="",
        )


def test_refuses_a_level_outside_the_open_unit_interval() -> None:
    for level in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(NpvIntervalError, match="уровень доверия"):
            ConformalNpvInterval(
                level=level,
                half_width_rub=1.0,
                n_calibration=100,
                calibration_population="train-holdout",
            )


def test_refuses_non_finite_residuals() -> None:
    with pytest.raises(NpvIntervalError, match="неконечные"):
        ConformalNpvInterval.fit(
            [0.0, float("inf")],
            [0.0, 0.0],
            level=0.9,
            population="train-holdout",
            population_used_in_training=False,
        )


def test_refuses_mismatched_lengths() -> None:
    with pytest.raises(NpvIntervalError, match="разной длины"):
        ConformalNpvInterval.fit(
            [0.0, 1.0],
            [0.0],
            level=0.9,
            population="train-holdout",
            population_used_in_training=False,
        )
