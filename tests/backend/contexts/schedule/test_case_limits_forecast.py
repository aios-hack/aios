from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import MappingProxyType
from typing import Mapping

import pytest

from backend.contexts.schedule.domain.schedule import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from backend.contexts.constraints.domain.constraints import Constraints, WellOutage
from backend.contexts.schedule.domain.case_limits import (
    CaseLimitsForecastRequired,
    CaseLimitsNotConverged,
    YearlyProduction,
    apply_case_limits,
    apply_case_limits_report,
)

pytestmark = [pytest.mark.slow]

WELLS = ("W1", "W2")
DATES = (date(2016, 1, 1), date(2017, 1, 1), date(2018, 1, 1), date(2019, 1, 1))
DAYS_PER_STEP = 1.0


def make_schedule(setpoints: Mapping[tuple[int, str], float]) -> Schedule:
    events = tuple(
        event
        for (step, well), value in sorted(setpoints.items())
        for event in (
            ControlEvent(step, well, EventKind.SET_LRAT, value),
            ControlEvent(step, well, EventKind.OPEN),
        )
    )
    state = WellState(Availability.AVAILABLE, Role.PROD, OperatingStatus.OPEN, 0.0)
    return Schedule(
        meta=ScheduleMeta(wells=WELLS),
        initial_state=MappingProxyType({well: state for well in WELLS}),
        fixed_deck_events=(),
        control_events=events,
    )


def uniform_schedule(value: float, steps: int = 3) -> Schedule:
    return make_schedule({(step, well): value for step in range(steps) for well in WELLS})


def liquid_setpoints(schedule: Schedule) -> dict[tuple[int, str], float]:
    return {
        (event.control_step, event.well): float(event.value or 0.0)
        for event in schedule.control_events
        if event.kind is EventKind.SET_LRAT
    }


def make_forecast(efficiency: float, calls: list[Schedule] | None = None):
    def forecast(schedule: Schedule) -> YearlyProduction:
        if calls is not None:
            calls.append(schedule)
        by_year: dict[int, float] = {}
        for event in schedule.control_events:
            if event.kind is not EventKind.SET_LRAT:
                continue
            year = DATES[event.control_step].year
            by_year[year] = by_year.get(year, 0.0) + float(event.value or 0.0) * efficiency * DAYS_PER_STEP
        for step in range(len(DATES) - 1):
            by_year.setdefault(DATES[step].year, 0.0)
        return YearlyProduction(liquid_by_year=MappingProxyType(by_year))

    return forecast


def test_no_trim_when_forecast_fits_the_limit() -> None:
    schedule = uniform_schedule(100.0)
    cap = 2 * 100.0 * 0.6 * DAYS_PER_STEP
    outcome = apply_case_limits_report(
        schedule,
        Constraints(liquid_limits={year: cap for year in (2016, 2017, 2018)}),
        DATES,
        make_forecast(0.6),
    )
    assert liquid_setpoints(outcome.schedule) == liquid_setpoints(schedule)
    assert outcome.forecast_used is True
    assert outcome.rounds == 0
    assert outcome.trimmed_years == {}


def test_setpoint_sum_would_have_trimmed_a_compliant_plan() -> None:
    schedule = uniform_schedule(100.0)
    cap = 2 * 100.0 * 0.6 * DAYS_PER_STEP
    limits = Constraints(liquid_limits={year: cap for year in (2016, 2017, 2018)})
    legacy = apply_case_limits(schedule, limits, DATES, allow_setpoint_sum_fallback=True)
    assert liquid_setpoints(legacy) != liquid_setpoints(schedule)
    honest = apply_case_limits(schedule, limits, DATES, make_forecast(0.6))
    assert liquid_setpoints(honest) == liquid_setpoints(schedule)


def test_trim_only_by_the_excess() -> None:
    schedule = uniform_schedule(100.0)
    forecast = make_forecast(1.0)
    produced = forecast(schedule).liquid_by_year[2017]
    cap = produced * 0.5
    outcome = apply_case_limits_report(
        schedule,
        Constraints(liquid_limits={2017: cap}),
        DATES,
        forecast,
    )
    trimmed = liquid_setpoints(outcome.schedule)
    for well in WELLS:
        assert trimmed[(1, well)] == pytest.approx(49.0, abs=1.0)
        assert trimmed[(0, well)] == 100.0
        assert trimmed[(2, well)] == 100.0
    assert forecast(outcome.schedule).liquid_by_year[2017] <= cap
    assert outcome.trimmed_years == {EventKind.SET_LRAT: (2017,)}


def test_iteration_converges_when_one_pass_is_not_enough() -> None:
    schedule = uniform_schedule(100.0)
    calls: list[Schedule] = []

    def forecast(current: Schedule) -> YearlyProduction:
        calls.append(current)
        by_year: dict[int, float] = {}
        for event in current.control_events:
            if event.kind is not EventKind.SET_LRAT:
                continue
            year = DATES[event.control_step].year
            value = float(event.value or 0.0)
            by_year[year] = by_year.get(year, 0.0) + 40.0 + 0.2 * value
        for step in range(len(DATES) - 1):
            by_year.setdefault(DATES[step].year, 0.0)
        return YearlyProduction(liquid_by_year=MappingProxyType(by_year))

    cap = 100.0
    outcome = apply_case_limits_report(
        schedule, Constraints(liquid_limits={2017: cap}), DATES, forecast
    )
    assert outcome.rounds >= 2
    assert len(calls) >= 3
    assert forecast(outcome.schedule).liquid_by_year[2017] <= cap


def test_non_convergence_is_reported_not_silently_accepted() -> None:
    schedule = uniform_schedule(100.0)

    def stubborn(current: Schedule) -> YearlyProduction:
        return YearlyProduction(
            liquid_by_year=MappingProxyType({DATES[step].year: 1e6 for step in range(3)})
        )

    with pytest.raises(CaseLimitsNotConverged):
        apply_case_limits(schedule, Constraints(liquid_limits={2017: 1.0}), DATES, stubborn, rounds=3)


def test_only_the_exceeding_year_is_trimmed() -> None:
    schedule = make_schedule(
        {(0, "W1"): 50.0, (0, "W2"): 50.0, (1, "W1"): 200.0, (1, "W2"): 200.0,
         (2, "W1"): 40.0, (2, "W2"): 40.0}
    )
    forecast = make_forecast(1.0)
    cap = 100.0 * DAYS_PER_STEP
    outcome = apply_case_limits_report(
        schedule,
        Constraints(liquid_limits={2016: cap, 2017: cap, 2018: cap}),
        DATES,
        forecast,
    )
    trimmed = liquid_setpoints(outcome.schedule)
    for well in WELLS:
        assert trimmed[(0, well)] == 50.0
        assert trimmed[(2, well)] == 40.0
        assert trimmed[(1, well)] < 200.0
    assert outcome.trimmed_years == {EventKind.SET_LRAT: (2017,)}
    result = forecast(outcome.schedule).liquid_by_year
    assert result[2017] <= cap


def test_missing_forecast_refuses_instead_of_trimming_by_setpoint_sum() -> None:
    schedule = uniform_schedule(100.0)
    with pytest.raises(CaseLimitsForecastRequired):
        apply_case_limits(schedule, Constraints(liquid_limits={2017: 1.0}), DATES)


def test_setpoint_sum_fallback_is_explicit_and_flagged() -> None:
    schedule = uniform_schedule(100.0)
    outcome = apply_case_limits_report(
        schedule,
        Constraints(liquid_limits={2017: 100.0}),
        DATES,
        allow_setpoint_sum_fallback=True,
    )
    assert outcome.setpoint_sum_fallback is True
    assert outcome.forecast_used is False
    assert liquid_setpoints(outcome.schedule)[(1, "W1")] == 50.0


def test_forecast_missing_a_capped_year_is_an_error() -> None:
    schedule = uniform_schedule(100.0)

    def partial(current: Schedule) -> YearlyProduction:
        return YearlyProduction(liquid_by_year=MappingProxyType({2016: 0.0}))

    with pytest.raises(CaseLimitsForecastRequired):
        apply_case_limits(schedule, Constraints(liquid_limits={2017: 1.0}), DATES, partial)


def test_outages_still_apply_without_any_year_limits() -> None:
    schedule = uniform_schedule(100.0)
    outcome = apply_case_limits_report(
        schedule, Constraints(well_outages=(WellOutage("W1", 0, 1),)), DATES
    )
    values = liquid_setpoints(outcome.schedule)
    assert values[(0, "W1")] == 0.0
    assert values[(1, "W1")] == 0.0
    assert values[(2, "W1")] == 100.0
    assert values[(0, "W2")] == 100.0
    shut = {
        (event.control_step, event.well)
        for event in outcome.schedule.control_events
        if event.kind is EventKind.SHUT
    }
    assert {(0, "W1"), (1, "W1")} <= shut


def test_injection_limits_use_the_injection_forecast() -> None:
    state = WellState(Availability.AVAILABLE, Role.INJ, OperatingStatus.OPEN, 0.0)
    events = tuple(
        event
        for step in range(3)
        for event in (
            ControlEvent(step, "W1", EventKind.SET_RATE, 300.0),
            ControlEvent(step, "W1", EventKind.OPEN),
        )
    )
    schedule = Schedule(
        meta=ScheduleMeta(wells=("W1",)),
        initial_state=MappingProxyType({"W1": state}),
        fixed_deck_events=(),
        control_events=events,
    )

    def forecast(current: Schedule) -> YearlyProduction:
        by_year: dict[int, float] = {}
        for event in current.control_events:
            if event.kind is not EventKind.SET_RATE:
                continue
            year = DATES[event.control_step].year
            by_year[year] = by_year.get(year, 0.0) + float(event.value or 0.0)
        for step in range(3):
            by_year.setdefault(DATES[step].year, 0.0)
        return YearlyProduction(injection_by_year=MappingProxyType(by_year))

    outcome = apply_case_limits_report(
        schedule,
        Constraints(injection_limits={2016: 1000.0, 2017: 150.0, 2018: 1000.0}),
        DATES,
        forecast,
    )
    values = {
        event.control_step: float(event.value or 0.0)
        for event in outcome.schedule.control_events
        if event.kind is EventKind.SET_RATE
    }
    assert values[0] == 300.0
    assert values[2] == 300.0
    assert values[1] <= 150.0
    assert outcome.trimmed_years == {EventKind.SET_RATE: (2017,)}


def test_backward_compatible_no_constraints_returns_input() -> None:
    schedule = uniform_schedule(100.0)
    assert apply_case_limits(schedule, Constraints(), DATES) is schedule
