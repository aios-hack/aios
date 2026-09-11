import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from backend.contexts.optimization.application import search_use_case as search
from datetime import date

from backend.core.contracts import (
    ControlEvent,
    EventKind,
    Lambda,
    Availability,
    Constraints,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)


def _lambda() -> Lambda:
    return Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2007, 3, 1),
        producers=("P1",),
        injectors=("I1", "I2"),
        matrix=((1.0, 0.5),),
        lag_months=0,
        amplitude=1.0,
        stability=1.0,
        rank=1,
        condition_number=1.0,
        achievability_ok={"I1": True, "I2": True},
    )


def _schedule() -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("P1", "I1", "I2")),
        initial_state={
            "P1": WellState(
                availability=Availability.AVAILABLE,
                role=Role.PROD,
                operating_status=OperatingStatus.OPEN,
                setpoint=50.0,
            ),
            "I1": WellState(
                availability=Availability.AVAILABLE,
                role=Role.INJ,
                operating_status=OperatingStatus.OPEN,
                setpoint=200.0,
            ),
            "I2": WellState(
                availability=Availability.AVAILABLE,
                role=Role.INJ,
                operating_status=OperatingStatus.OPEN,
                setpoint=100.0,
            ),
        },
        fixed_deck_events=(),
        control_events=(
            ControlEvent(
                control_step=0, well="I1", kind=EventKind.SET_RATE, value=200.0
            ),
            ControlEvent(
                control_step=0, well="I2", kind=EventKind.SET_RATE, value=100.0
            ),
        ),
    )


def test_fallback_cannot_return_baseline_violating_case(tmp_path):
    diagnostics = tmp_path / 'diagnostics.json'
    diagnostics.write_text(json.dumps({'evaluations': []}))
    schedule = _schedule()
    env = SimpleNamespace(
        base_schedule=schedule,
        constraints=Constraints(),
        control_dates=(),
        groups=None,
        scenario_ood=None,
        ood_threshold=0.0,
        model=None,
        lambda_=_lambda(),
    )
    with patch.object(search, 'SEARCH_DIAGNOSTICS', diagnostics), patch.object(search, 'validate_static') as validate:
        validate.return_value = SimpleNamespace(ok=False, violations=('outage',))
        with pytest.raises(search.SearchRunError):
            search._search_near_baseline(env, None, 3, {})
    recorded = json.loads(diagnostics.read_text(encoding='utf-8'))['evaluations'][0]
    assert not recorded['feasible']
    assert recorded['npv_predicted'] is None


def test_fallback_keeps_ood_guard(tmp_path):
    diagnostics = tmp_path / 'diagnostics.json'
    diagnostics.write_text(json.dumps({'evaluations': []}))
    env = SimpleNamespace(
        base_schedule=_schedule(),
        constraints=Constraints(),
        control_dates=(),
        groups=None,
        scenario_ood=None,
        ood_threshold=0.0,
        model=None,
        lambda_=_lambda(),
    )
    with patch.object(search, 'SEARCH_DIAGNOSTICS', diagnostics), patch.object(search, 'validate_static') as validate, patch.object(search, '_repair_predicted_water_balance') as evaluate:
        validate.return_value = SimpleNamespace(ok=True, violations=())
        evaluate.side_effect = search.OutOfDomainScheduleError(99, 'outside training')
        with pytest.raises(search.SearchRunError):
            search._search_near_baseline(env, None, 3, {})
    assert not json.loads(diagnostics.read_text(encoding='utf-8'))['evaluations'][0]['feasible']
