from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from backend.core.contracts import (
    ActiveControlMode,
    Availability,
    ControlEvent,
    EventKind,
    N_CONTROL_DATES,
    N_INTERVALS,
    OperatingStatus,
    ResponseArtifact,
    Role,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    WellState,
    hash_schedule,
)
from backend.ml.surrogate import AdapterError, RawModelOutput, RawWellStepPrediction, ResponseAdapter

_WELLS = ("L", "P")  # лексикографический порядок
_LATE_OPEN_STEP = 50  # control_step, на котором "L" впервые получает OPEN
_HISTORY_HORIZON = 147  # deck_date_index 0…146


def _wells() -> tuple[str, ...]:
    return _WELLS


def _control_dates() -> tuple[date, ...]:
    """225 календарных начал месяца — интервалы неравные (28…31 день)."""

    dates = []
    year, month = 2007, 1
    for _ in range(N_CONTROL_DATES):
        dates.append(date(year, month, 1))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return tuple(dates)


def _schedule() -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=_WELLS, provenance="test"),
        initial_state={
            "P": WellState(Availability.AVAILABLE, Role.PROD, OperatingStatus.OPEN, 10.0),
            "L": WellState(Availability.NOT_COMMISSIONED, Role.NONE, OperatingStatus.SHUT, 0.0),
        },
        fixed_deck_events=(),
        control_events=(
            # "L" впервые открывается на _LATE_OPEN_STEP — до этого NOT_COMMISSIONED.
            ControlEvent(_LATE_OPEN_STEP, "L", EventKind.SET_LRAT, value=5.0),
            ControlEvent(_LATE_OPEN_STEP, "L", EventKind.OPEN),
            # На control_step=10 у "P" занижается уставка — точка для BHP_LIMITED.
            ControlEvent(10, "P", EventKind.SET_LRAT, value=100.0),
        ),
    )


def _historical_state(deck_date_index: int, well: str, *, poison: bool = False) -> StateAtDate:
    if poison:
        # Заведомо отличимые от прогноза значения — доказывают, что адаптер
        # их не читает для прогнозной части (147…370).
        return StateAtDate(
            deck_date_index=deck_date_index,
            well=well,
            liquid_rate=-999.0,
            oil_rate=-999.0,
            injection_rate=-999.0,
            thp=-999.0,
            bhp=-999.0,
            well_efficiency=-999.0,
            active_control_mode=ActiveControlMode.UNKNOWN,
        )
    return StateAtDate(
        deck_date_index=deck_date_index,
        well=well,
        liquid_rate=1.0,
        oil_rate=0.5,
        injection_rate=0.0,
        thp=20.0,
        bhp=40.0,
        well_efficiency=0.9,
        active_control_mode=ActiveControlMode.RATE_TARGET,
    )


def _historical(wells: tuple[str, ...] = _WELLS) -> ResponseArtifact:
    state_at_date = tuple(
        _historical_state(d, well, poison=(d >= _HISTORY_HORIZON))
        for well in wells
        for d in range(371)
    )
    return ResponseArtifact(
        source_run_id="base-run",
        response_hash="hash",
        state_at_date=state_at_date,
        interval_response=(),
    )


def _raw_node(well: str, control_step: int, **overrides) -> RawWellStepPrediction:
    values = dict(
        well=well,
        control_step=control_step,
        oil_mass_delta=10.0 + control_step,
        liquid_volume_delta=20.0 + control_step,
        injection_volume_delta=0.0,
        liquid_rate=30.0 + control_step,
        injection_rate=0.0,
        bhp=45.0,
    )
    values.update(overrides)
    return RawWellStepPrediction(**values)


def _raw(
    wells: tuple[str, ...] = _WELLS,
    schedule_hash: str | None = None,
    overrides: dict[tuple[str, int], RawWellStepPrediction] | None = None,
) -> RawModelOutput:
    overrides = overrides or {}
    nodes = tuple(
        overrides.get((well, step), _raw_node(well, step))
        for well in wells
        for step in range(N_INTERVALS)
    )
    return RawModelOutput(
        canonical_schedule_hash=schedule_hash or hash_schedule(_schedule()),
        wells=wells,
        nodes=nodes,
    )


def _adapt():
    schedule = _schedule()
    state_at_date, interval_response = ResponseAdapter().adapt(
        _raw(schedule_hash=hash_schedule(schedule)),
        schedule,
        _historical(),
        _control_dates(),
    )
    return schedule, state_at_date, interval_response


def _state(state_at_date, deck_date_index: int, well: str) -> StateAtDate:
    return next(
        s for s in state_at_date if s.deck_date_index == deck_date_index and s.well == well
    )


def _interval(interval_response, control_step: int, well: str):
    return next(
        r for r in interval_response if r.control_step == control_step and r.well == well
    )


def test_predicted_horizon_comes_from_model_not_history() -> None:
    _, state_at_date, _ = _adapt()
    for step in (0, 112, 223):
        for well in _WELLS:
            state = _state(state_at_date, _HISTORY_HORIZON + step, well)
            node = _raw_node(well, step)
            assert state.liquid_rate == node.liquid_rate
            assert state.injection_rate == node.injection_rate
            assert state.bhp == node.bhp
            assert state.liquid_rate != -999.0


def test_historical_part_is_copied_verbatim_from_base_run() -> None:
    schedule = _schedule()
    historical = _historical()
    state_at_date, _ = ResponseAdapter().adapt(
        _raw(schedule_hash=hash_schedule(schedule)), schedule, historical, _control_dates()
    )
    historical_by_key = {(s.deck_date_index, s.well): s for s in historical.state_at_date}
    for d in (0, 73, 146):
        for well in _WELLS:
            assert _state(state_at_date, d, well) is historical_by_key[(d, well)]


def test_boundary_k0_and_k223_are_not_off_by_one() -> None:
    schedule = _schedule()
    historical = _historical()
    state_at_date, _ = ResponseAdapter().adapt(
        _raw(schedule_hash=hash_schedule(schedule)), schedule, historical, _control_dates()
    )
    historical_by_key = {(s.deck_date_index, s.well): s for s in historical.state_at_date}

    assert _state(state_at_date, 146, "P") is historical_by_key[(146, "P")]
    assert _state(state_at_date, 147, "P").liquid_rate == _raw_node("P", 0).liquid_rate
    assert _state(state_at_date, 370, "P").liquid_rate == _raw_node("P", 223).liquid_rate


def test_axis_sizes_and_index_coverage() -> None:
    _, state_at_date, interval_response = _adapt()
    for well in _WELLS:
        state_indices = {s.deck_date_index for s in state_at_date if s.well == well}
        interval_indices = {r.control_step for r in interval_response if r.well == well}
        assert state_indices == set(range(371))
        assert interval_indices == set(range(N_INTERVALS))


def test_well_major_ordering_matches_response_loader_convention() -> None:
    _, state_at_date, interval_response = _adapt()
    assert [s.well for s in state_at_date] == [w for w in _WELLS for _ in range(371)]
    assert [r.well for r in interval_response] == [w for w in _WELLS for _ in range(N_INTERVALS)]
    for well in _WELLS:
        indices = [s.deck_date_index for s in state_at_date if s.well == well]
        assert indices == sorted(indices)


def test_interval_response_is_passthrough_not_recomputed() -> None:
    _, _, interval_response = _adapt()
    for step in (0, 112, 223):
        for well in _WELLS:
            row = _interval(interval_response, step, well)
            node = _raw_node(well, step)
            assert row.oil_mass_delta == node.oil_mass_delta
            assert row.liquid_volume_delta == node.liquid_volume_delta
            assert row.injection_volume_delta == node.injection_volume_delta


def test_oil_rate_is_derived_not_a_model_field() -> None:
    control_dates = _control_dates()
    _, state_at_date, _ = _adapt()
    for step in (0, 1, 112):  # разные длины интервала (28…31 день)
        days = (control_dates[step + 1] - control_dates[step]).days
        node = _raw_node("P", step)
        state = _state(state_at_date, _HISTORY_HORIZON + step, "P")
        assert state.oil_rate == pytest.approx(node.oil_mass_delta / days)


def test_thp_and_well_efficiency_held_forward_from_last_historical_value() -> None:
    _, state_at_date, _ = _adapt()
    last_historical = _historical_state(146, "P")
    for step in (0, 223):
        state = _state(state_at_date, _HISTORY_HORIZON + step, "P")
        assert state.thp == last_historical.thp
        assert state.well_efficiency == last_historical.well_efficiency


def test_active_control_mode_uses_fallback_rule_bhp_limited() -> None:
    schedule = _schedule()
    overrides = {("P", 10): _raw_node("P", 10, liquid_rate=50.0, bhp=48.0)}
    state_at_date, _ = ResponseAdapter().adapt(
        _raw(schedule_hash=hash_schedule(schedule), overrides=overrides),
        schedule,
        _historical(),
        _control_dates(),
    )
    state = _state(state_at_date, _HISTORY_HORIZON + 10, "P")
    # setpoint=100.0 (SET_LRAT на control_step=10), liquid_rate=50.0 -> ratio=0.5<0.999,
    # bhp=48.0 в пределах 5 бар от предела продюсера 50.0 -> BHP_LIMITED.
    assert state.active_control_mode is ActiveControlMode.BHP_LIMITED


def test_not_yet_commissioned_well_during_predicted_horizon() -> None:
    _, state_at_date, _ = _adapt()
    before = _state(state_at_date, _HISTORY_HORIZON + _LATE_OPEN_STEP - 1, "L")
    at = _state(state_at_date, _HISTORY_HORIZON + _LATE_OPEN_STEP, "L")
    assert before.active_control_mode is ActiveControlMode.NOT_COMMISSIONED
    assert at.active_control_mode is not ActiveControlMode.NOT_COMMISSIONED


def test_rejects_schedule_hash_mismatch() -> None:
    schedule = _schedule()
    with pytest.raises(AdapterError, match="не под этот Schedule"):
        ResponseAdapter().adapt(
            _raw(schedule_hash="wrong-hash"), schedule, _historical(), _control_dates()
        )


def test_rejects_well_axis_mismatch() -> None:
    schedule = _schedule()
    raw = replace(_raw(schedule_hash=hash_schedule(schedule)), wells=("P", "L"))
    with pytest.raises(AdapterError, match="Schedule.meta.wells"):
        ResponseAdapter().adapt(raw, schedule, _historical(), _control_dates())


def test_rejects_incomplete_historical_coverage() -> None:
    schedule = _schedule()
    historical = _historical()
    incomplete = replace(
        historical,
        state_at_date=tuple(s for s in historical.state_at_date if not (s.deck_date_index == 0 and s.well == "P")),
    )
    with pytest.raises(AdapterError, match="историческая часть неполна"):
        ResponseAdapter().adapt(
            _raw(schedule_hash=hash_schedule(schedule)), schedule, incomplete, _control_dates()
        )


def test_rejects_bad_control_dates() -> None:
    schedule = _schedule()
    raw = _raw(schedule_hash=hash_schedule(schedule))
    with pytest.raises(AdapterError, match="225 дат"):
        ResponseAdapter().adapt(raw, schedule, _historical(), _control_dates()[:-1])

    non_monotonic = list(_control_dates())
    non_monotonic[1] = non_monotonic[0]
    with pytest.raises(AdapterError, match="строго возрастать"):
        ResponseAdapter().adapt(raw, schedule, _historical(), tuple(non_monotonic))
