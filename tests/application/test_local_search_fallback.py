import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from backend.application.optimization import search_run as search
from backend.core.contracts import Constraints


def test_fallback_cannot_return_baseline_violating_case(tmp_path):
    diagnostics = tmp_path / 'diagnostics.json'
    diagnostics.write_text(json.dumps({'evaluations': []}))
    schedule = SimpleNamespace(control_events=())
    env = SimpleNamespace(base_schedule=schedule, constraints=Constraints())
    with patch.object(search, 'SEARCH_DIAGNOSTICS', diagnostics), patch.object(search, 'validate_static') as validate:
        validate.return_value = SimpleNamespace(ok=False, violations=('outage',))
        with pytest.raises(search.SearchRunError):
            search._search_near_baseline(env, None, 1, {})
    recorded = json.loads(diagnostics.read_text())['evaluations'][0]
    assert not recorded['feasible']
    assert recorded['npv_predicted'] is None


def test_fallback_keeps_ood_guard(tmp_path):
    diagnostics = tmp_path / 'diagnostics.json'
    diagnostics.write_text(json.dumps({'evaluations': []}))
    env = SimpleNamespace(base_schedule=SimpleNamespace(control_events=()), constraints=Constraints())
    with patch.object(search, 'SEARCH_DIAGNOSTICS', diagnostics), patch.object(search, 'validate_static') as validate, patch.object(search, '_repair_predicted_water_balance') as evaluate:
        validate.return_value = SimpleNamespace(ok=True)
        evaluate.side_effect = search.OutOfDomainScheduleError(99, 'outside training')
        with pytest.raises(search.SearchRunError):
            search._search_near_baseline(env, None, 1, {})
    assert not json.loads(diagnostics.read_text())['evaluations'][0]['feasible']
