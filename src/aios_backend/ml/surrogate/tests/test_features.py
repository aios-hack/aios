from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from aios_backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    Lambda,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from aios_backend.ml.surrogate import (
    FeatureContext,
    FeatureError,
    HistoryTargets,
    ScheduleFeatureizer,
    history_targets_from_deck,
)


def _dates() -> tuple[date, date, date]:
    return (date(2007, 1, 1), date(2007, 2, 1), date(2007, 3, 1))


def _lambda(
    start: date = date(2007, 1, 1),
    end: date = date(2007, 12, 31),
    coefficient: float = 0.25,
) -> Lambda:
    return Lambda(
        window_start=start,
        window_end=end,
        producers=("P", "LATE"),
        injectors=("I",),
        matrix=((coefficient,), (coefficient * 2.0,)),
        lag_months=1,
        amplitude=0.1,
        stability=0.9,
        rank=1,
        condition_number=1.0,
        achievability_ok={"I": True},
    )


def _schedule() -> Schedule:
    return Schedule(
        meta=ScheduleMeta(
            n_control_dates=3,
            n_intervals=2,
            wells=("P", "I", "LATE"),
            history_prefix_hash="history",
        ),
        initial_state={
            "P": WellState(
                Availability.AVAILABLE, Role.PROD, OperatingStatus.OPEN, 10.0
            ),
            "I": WellState(
                Availability.AVAILABLE, Role.INJ, OperatingStatus.OPEN, 20.0
            ),
            "LATE": WellState(
                Availability.NOT_COMMISSIONED, Role.NONE, OperatingStatus.SHUT, 0.0
            ),
        },
        fixed_deck_events=(
            FixedDeckEvent(
                control_step=0,
                well="P",
                operator="COMPDAT",
                raw_args=("1", "1", "1", "1", "OPEN"),
            ),
            FixedDeckEvent(
                control_step=1,
                well="LATE",
                operator="WCONPROD",
                raw_args=("OPEN", "LRAT", "1*", "1*", "1*", "7.0"),
            ),
        ),
        control_events=(ControlEvent(1, "P", EventKind.SHUT),),
    )


def _context(lambda_windows: tuple[Lambda, ...] | None = None) -> FeatureContext:
    return FeatureContext(
        control_dates=_dates(),
        history_start=date(1994, 11, 1),
        history_prefix_hash="history",
        history_targets={
            "P": HistoryTargets(1_000.0, 0.0, 3),
            "I": HistoryTargets(0.0, 2_000.0, 4),
            "LATE": HistoryTargets(0.0, 0.0, 0),
        },
        static_features={
            "P": {"i": 10.0, "j": 20.0},
            "I": {"i": 11.0, "j": 21.0},
            "LATE": {"i": 12.0, "j": 22.0},
        },
        lambda_windows=lambda_windows or (_lambda(),),
    )


def _node(result, control_step: int, well: str):
    return next(
        node
        for node in result.nodes
        if node.control_step == control_step and node.well == well
    )


def test_features_use_one_schedule_history_fixed_layer_static_and_lambda() -> None:
    result = ScheduleFeatureizer().transform(_schedule(), _context())

    p0 = _node(result, 0, "P")
    p1 = _node(result, 1, "P")
    late0 = _node(result, 0, "LATE")
    late1 = _node(result, 1, "LATE")

    # Накопления не обнуляются на t0: 1994--2006 приходит из исходного дека.
    assert p0.cumulative_target_liquid_m3 == 1_000.0 + 10.0 * 31
    assert p1.cumulative_target_liquid_m3 == p0.cumulative_target_liquid_m3
    # Невведённая и остановленная скважины обе имеют нулевой эффективный
    # дебит, но различаются отдельным признаком availability.
    assert late0.effective_target_rate_m3_per_day == 0.0
    assert late0.availability is Availability.NOT_COMMISSIONED
    assert p1.effective_target_rate_m3_per_day == 0.0
    assert p1.availability is Availability.AVAILABLE
    assert p1.operating_status is OperatingStatus.SHUT
    # Ввод приходит из fixed_deck_events, а не из симулятора.
    assert late1.availability is Availability.AVAILABLE
    assert late1.cumulative_target_liquid_m3 == 7.0 * 28
    assert late1.fixed_event_count == 1
    assert p0.fixed_event_count == 1
    assert p0.static_values == (10.0, 20.0)
    assert result.static_feature_names == ("i", "j")
    # Полная lambda сохранена ребром, агрегат использует накопление своего
    # нагнетателя, включая ненулевую историю.
    edge0 = next(
        edge
        for edge in result.lambda_edges
        if edge.control_step == 0 and edge.producer == "P"
    )
    assert edge0.coefficient == 0.25
    assert edge0.injector_cumulative_target_injection_m3 == 2_000.0 + 20.0 * 31
    assert p0.cumulative_neighbor_injection_m3 == pytest.approx(
        0.25 * edge0.injector_cumulative_target_injection_m3
    )
    assert not any(
        edge.control_step == 0 and edge.producer == "LATE"
        for edge in result.lambda_edges
    )
    assert any(
        edge.control_step == 1 and edge.producer == "LATE"
        for edge in result.lambda_edges
    )
    assert len(result.nodes) == 2 * 3


def test_conversion_batch_closes_producer_before_applying_injector_target() -> None:
    schedule = replace(
        _schedule(),
        control_events=(
            ControlEvent(1, "P", EventKind.CONVERT_INJ),
            ControlEvent(1, "P", EventKind.SET_LRAT, 0.0),
            ControlEvent(1, "P", EventKind.SET_RATE, 30.0),
            ControlEvent(1, "P", EventKind.OPEN),
        ),
    )

    result = ScheduleFeatureizer().transform(schedule, _context())
    converted = _node(result, 1, "P")

    assert converted.role is Role.INJ
    assert converted.operating_status is OperatingStatus.OPEN
    assert converted.setpoint_m3_per_day == 30.0
    assert converted.effective_target_rate_m3_per_day == 30.0


def test_only_selected_lambda_window_is_used() -> None:
    windows = (
        _lambda(date(2007, 1, 1), date(2007, 1, 31), 0.1),
        _lambda(date(2007, 2, 1), date(2007, 12, 31), 0.7),
    )
    result = ScheduleFeatureizer().transform(_schedule(), _context(windows))

    coefficients = [
        edge.coefficient for edge in result.lambda_edges if edge.producer == "P"
    ]
    assert coefficients == [0.1, 0.7]
    assert _node(result, 0, "P").lambda_window_start == date(2007, 1, 1)
    assert _node(result, 1, "P").lambda_window_start == date(2007, 2, 1)


def test_lambda_gap_or_overlap_is_rejected() -> None:
    gap = (_lambda(date(2007, 1, 2), date(2007, 12, 31)),)
    with pytest.raises(FeatureError, match="ровно одно окно lambda"):
        ScheduleFeatureizer().transform(_schedule(), _context(gap))

    overlap = (
        _lambda(date(2007, 1, 1), date(2007, 2, 1)),
        _lambda(date(2007, 2, 1), date(2007, 12, 31)),
    )
    with pytest.raises(FeatureError, match="найдено 2"):
        ScheduleFeatureizer().transform(_schedule(), _context(overlap))


def test_history_prefix_must_belong_to_the_same_schedule() -> None:
    context = replace(_context(), history_prefix_hash="another-history")
    with pytest.raises(FeatureError, match="не из префикса этого Schedule"):
        ScheduleFeatureizer().transform(_schedule(), context)


def test_history_is_calculated_from_targets_in_deck_without_simulator() -> None:
    raw = b"""DATES
 01 NOV 1994 /
/
WCONPROD
 'P' 'OPEN' 'LRAT' 1* 1* 1* 10 1* 50 /
/
WCONINJE
 'I' 'WATER' 'OPEN' 'RATE' 20 1* 300 /
/
DATES
 01 DEC 1994 /
/
WCONPROD
 'P' 'SHUT' 'LRAT' 1* 1* 1* 10 1* 50 /
/
DATES
 01 JAN 2007 /
/
WCONPROD
 'P' 'OPEN' 'LRAT' 1* 1* 1* 99 1* 50 /
/
"""

    history_start, history = history_targets_from_deck(raw, ("P", "I", "LATE"))

    assert history_start == date(1994, 11, 1)
    assert history["P"] == HistoryTargets(10.0 * 30, 0.0, 2)
    assert history["I"].target_injection_m3 == 20.0 * (
        date(2007, 1, 1) - date(1994, 11, 1)
    ).days
    assert history["I"].event_count == 1
    assert history["LATE"] == HistoryTargets(0.0, 0.0, 0)


def test_featureizer_has_no_response_or_simulator_input() -> None:
    schedule = _schedule()
    first = ScheduleFeatureizer().transform(schedule, _context())
    changed = replace(
        schedule,
        control_events=(*schedule.control_events, ControlEvent(0, "P", EventKind.SET_LRAT, 12.0)),
    )
    second = ScheduleFeatureizer().transform(changed, _context())

    assert first.canonical_schedule_hash != second.canonical_schedule_hash
    assert _node(first, 0, "P").cumulative_target_liquid_m3 != _node(
        second, 0, "P"
    ).cumulative_target_liquid_m3
