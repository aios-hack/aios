"""Приёмка локальной калибровки ЧДД по якорям кейса."""

from __future__ import annotations

import pytest

from surrogate.local_calibration import (
    MIN_ANCHORS,
    LocalCalibrationError,
    LocalNpvCalibration,
)

# Восемь настоящих точек: прогноз блендированного суррогата и факт OPM
# (`data/surrogate/metrics.json`, семейство constrained-opm-*). Синтетику здесь
# использовать нельзя — калибровка проверяется на том самом сдвиге домена,
# ради которого она существует.
SURROGATE_RUB = (
    -6_172_100_000.0,
    -6_285_700_000.0,
    -11_443_800_000.0,
    -16_891_500_000.0,
    -11_272_200_000.0,
    -7_021_700_000.0,
    -2_214_600_000.0,
    -20_804_800_000.0,
)
OPM_RUB = (
    3_770_100_000.0,
    3_730_600_000.0,
    2_418_700_000.0,
    2_202_500_000.0,
    2_440_700_000.0,
    3_507_200_000.0,
    6_052_900_000.0,
    1_366_200_000.0,
)


def _fit() -> LocalNpvCalibration:
    return LocalNpvCalibration.fit(SURROGATE_RUB, OPM_RUB, case="constrained-opm")


def test_slope_is_positive_so_the_order_survives() -> None:
    """Порядок кандидатов — единственное, что суррогат восстанавливает точно."""

    calibration = _fit()

    assert calibration.slope > 0.0
    ordered = sorted(SURROGATE_RUB)
    calibrated = [calibration.apply(value) for value in ordered]
    assert calibrated == sorted(calibrated)


def test_calibration_cuts_the_domain_shift_by_an_order_of_magnitude() -> None:
    """431% сырой ошибки против ~25% после поправки — ради этого всё и делается."""

    calibration = _fit()
    raw = [
        abs(s - o) / abs(o) * 100.0
        for s, o in zip(SURROGATE_RUB, OPM_RUB, strict=True)
    ]
    raw_median = sorted(raw)[len(raw) // 2]

    assert raw_median > 300.0
    assert calibration.leave_one_out.median_relative_error_pct < 40.0
    assert calibration.leave_one_out.median_relative_error_pct * 10 < raw_median


def test_leave_one_out_is_measured_on_points_the_fold_did_not_see() -> None:
    calibration = _fit()
    loo = calibration.leave_one_out

    assert loo.n_anchors == len(SURROGATE_RUB)
    assert loo.max_relative_error_pct >= loo.median_relative_error_pct
    assert loo.median_absolute_error_rub > 0.0


def test_calibrated_value_is_not_submission_grade() -> None:
    """Главная защита: 25% — это не 2%, и метод обязан сказать это вслух."""

    calibration = _fit()

    assert calibration.submission_grade() is False
    assert calibration.submission_grade(tolerance_pct=50.0) is True


def test_report_carries_the_error_next_to_the_coefficients() -> None:
    payload = _fit().as_dict()

    assert payload["format"] == "aios.surrogate-local-npv-calibration.v1"
    assert payload["case"] == "constrained-opm"
    assert payload["submission_grade"] is False
    assert payload["leave_one_out"]["n_anchors"] == 8


# --- отказы -------------------------------------------------------------------


def test_refuses_too_few_anchors_for_an_honest_leave_one_out() -> None:
    with pytest.raises(LocalCalibrationError, match="минимум"):
        LocalNpvCalibration.fit(
            SURROGATE_RUB[: MIN_ANCHORS - 1],
            OPM_RUB[: MIN_ANCHORS - 1],
            case="constrained-opm",
        )


def test_refuses_an_unnamed_case() -> None:
    with pytest.raises(LocalCalibrationError, match="привязана к кейсу"):
        LocalNpvCalibration(
            slope=1.0,
            intercept_rub=0.0,
            case="",
            leave_one_out=_fit().leave_one_out,
        )


def test_refuses_a_negative_slope_that_would_invert_the_ranking() -> None:
    with pytest.raises(LocalCalibrationError, match="перевернул бы порядок"):
        LocalNpvCalibration(
            slope=-1.0,
            intercept_rub=0.0,
            case="constrained-opm",
            leave_one_out=_fit().leave_one_out,
        )


def test_refuses_anchors_with_identical_predictions() -> None:
    with pytest.raises(LocalCalibrationError, match="наклон не определён"):
        LocalNpvCalibration.fit(
            (1.0, 1.0, 1.0, 1.0), OPM_RUB[:4], case="constrained-opm"
        )


def test_refuses_mismatched_lengths() -> None:
    with pytest.raises(LocalCalibrationError, match="разной длины"):
        LocalNpvCalibration.fit(SURROGATE_RUB, OPM_RUB[:-1], case="constrained-opm")


def test_refuses_non_finite_anchors() -> None:
    with pytest.raises(LocalCalibrationError, match="неконечные"):
        LocalNpvCalibration.fit(
            (*SURROGATE_RUB[:-1], float("nan")), OPM_RUB, case="constrained-opm"
        )
