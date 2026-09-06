import json
from unittest.mock import patch
import pytest
from backend.presentation.cli.web_runs import WebRuns


def test_search_freezes_constraints_and_rejects_concurrent_run(tmp_path):
    jobs = WebRuns(tmp_path)
    with patch('backend.presentation.cli.web_runs.threading.Thread') as thread:
        run = jobs.start({'constraints': {'injection_limits': {'2007': 30000}}, 'budget': 10})
        saved = json.loads((tmp_path / run['run_id'] / 'constraints.json').read_text())
        assert saved['injection_limits'] == {'2007': 30000}
        assert run['status'] == 'running'
        thread.return_value.start.assert_called_once()
        with pytest.raises(RuntimeError):
            jobs.start({'constraints': {}, 'budget': 10})


def test_bad_infrastructure_never_starts_job(tmp_path):
    jobs = WebRuns(tmp_path)
    for infrastructure in ({'external_water_m3_per_day': 1}, {'compensation_min': .8}, {'unknown': 10}):
        with pytest.raises(ValueError):
            jobs.start({'constraints': {'infrastructure': infrastructure}})
    assert jobs.list() == []
    assert not jobs.lock.locked()


def test_verify_rejects_traversal_and_missing_plan(tmp_path):
    jobs = WebRuns(tmp_path)
    for run_id in ('../../escape', 'web-missing'):
        with pytest.raises(ValueError):
            jobs.start({'mode': 'verify', 'run_id': run_id})
    assert not jobs.lock.locked()


def test_failed_worker_is_not_a_verified_result(tmp_path):
    jobs = WebRuns(tmp_path)
    directory = tmp_path / 'web-test'
    directory.mkdir()
    jobs.lock.acquire()
    data = {'run_id': 'web-test', 'status': 'running'}
    with patch('backend.presentation.cli.web_runs.subprocess.run') as run:
        run.return_value.returncode = 1
        jobs._execute(directory, data, 'verify', 30)
    result = jobs.list()[0]
    assert result['status'] == 'failed'
    assert 'manifest' not in result
    assert not jobs.lock.locked()
