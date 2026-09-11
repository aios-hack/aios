from __future__ import annotations

from math import isnan
from pathlib import Path

import pytest

from backend.contexts.simulation.application.baseline_diagnostics import (
    MATERIAL_BALANCE_RELATIVE_TOLERANCE,
    run_base_case,
)
from backend.contexts.runs.domain.run_result import RunStatus
from backend.shared.paths import data_root


from tests.support.backend.environment import (
    docker_unavailable_reason,
    missing_reason,
    model_z_dir,
)

MODEL_Z = model_z_dir()

DOCKER_REASON = docker_unavailable_reason()

pytestmark = [pytest.mark.skipif(MODEL_Z is None, reason=missing_reason('Model_Z directory')), pytest.mark.skipif(DOCKER_REASON is not None, reason=f'acceptance of task 7 requires a real OPM Flow; {DOCKER_REASON}'), pytest.mark.slow, pytest.mark.opm]
WORK_ROOT = data_root() / "base_run"


@pytest.fixture(scope="module")
def report():
    return run_base_case(MODEL_Z, WORK_ROOT)


def test_measures_real_wallclock_time(report) -> None:

    assert report.run_result.status is RunStatus.OK, report.run_result.message
    assert report.wallclock_seconds > 0.0


def test_material_balance_converges_without_aquifer_correction(report) -> None:

    assert report.material_balance.oil_relative_error < MATERIAL_BALANCE_RELATIVE_TOLERANCE, (
        report.material_balance.oil_relative_error
    )
    assert report.material_balance.water_relative_error < MATERIAL_BALANCE_RELATIVE_TOLERANCE, (
        report.material_balance.water_relative_error
    )


def test_reservoir_pressure_does_not_blow_up(report) -> None:

    pressure = report.pressure
    assert pressure.within_bounds, (
        f"FPR went out of bounds: initial={pressure.initial_bar}, "
        f"min={pressure.min_bar}, max={pressure.max_bar}"
    )


def test_watercut_increases_as_a_rule_not_as_hard_oracle(report) -> None:

    trend = report.watercut_trend
    assert trend.increasing_as_a_rule, (
        f"watercut does not grow over the long horizon: "
        f"first half={trend.first_half_mean:.4f}, second={trend.second_half_mean:.4f}"
    )


def test_thirty_injection_conversions_land_on_their_dates(report) -> None:

    assert len(report.conversions) == 30, sorted(c.transition.well for c in report.conversions)
    failed = [c for c in report.conversions if not c.verified]
    assert not failed, [
        (c.transition.well, str(c.transition.event_date), c.injection_rate_at_date) for c in failed
    ]


def test_twenty_two_wells_commissioned_on_their_dates(report) -> None:

    assert len(report.introductions) == 22, sorted(i.introduction.well for i in report.introductions)
    failed = [i for i in report.introductions if not i.verified]
    assert not failed, [
        (i.introduction.well, i.introduction.deck_date_index, str(i.mode_before), str(i.mode_at))
        for i in failed
    ]


def test_field_series_has_no_missing_or_nan_values(report) -> None:

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
