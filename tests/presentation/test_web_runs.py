import ast
import functools
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch
import pytest
from backend.presentation.cli import web
from backend.presentation.cli.web_runs import WebRuns

WEB_SOURCE = Path(web.__file__)


def test_search_freezes_constraints_and_rejects_concurrent_run(tmp_path):
    jobs = WebRuns(tmp_path)
    with patch('backend.presentation.cli.web_runs.threading.Thread') as thread:
        run = jobs.start({'constraints': {'injection_limits': {'2007': 30000}}, 'budget': 10})
        saved = json.loads((tmp_path / run['run_id'] / 'constraints.json').read_text(encoding='utf-8'))
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


def test_importing_adapter_does_not_mark_active_jobs_failed(tmp_path):
    directory = tmp_path / 'web-active'
    directory.mkdir()
    path = directory / 'job.json'
    path.write_text(json.dumps({'run_id': 'web-active', 'status': 'running'}), encoding='utf-8')
    jobs = WebRuns(tmp_path)
    assert json.loads(path.read_text(encoding='utf-8'))['status'] == 'running'
    jobs.recover_interrupted()
    assert json.loads(path.read_text(encoding='utf-8'))['status'] == 'failed'


def test_opm_progress_comes_from_real_log_and_keeps_model_date(tmp_path):
    directory = tmp_path / 'web-progress'
    output = directory / 'opm/runs/opm-one'
    output.mkdir(parents=True)
    (directory / 'job.json').write_text(json.dumps({'run_id': 'web-progress', 'status': 'running', 'mode': 'verify'}), encoding='utf-8')
    (output / 'flow.log').write_text('Report step 17/371 at day 400/12511, date = 01-Jan-2007\n')
    assert WebRuns(tmp_path).list()[0]['progress'] == {'step': 17, 'total': 371, 'date': '01.01.2007'}


@pytest.fixture()
def server(tmp_path, monkeypatch) -> Iterator[str]:
    (tmp_path / 'index.html').write_text('<!doctype html><title>aios</title>', encoding='utf-8')
    monkeypatch.setattr(web.SpaRequestHandler, 'runs', WebRuns(tmp_path / 'runs'))
    (tmp_path / 'runs').mkdir()
    handler = functools.partial(web.SpaRequestHandler, directory=str(tmp_path))
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    try:
        yield f'http://{host}:{port}'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def fetch(url: str, body: dict[str, Any] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url)
    if body is not None:
        request.data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        request.method = 'POST'
        request.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_handler_declares_every_method_once() -> None:
    tree = ast.parse(WEB_SOURCE.read_text(encoding='utf-8'))
    handler = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == 'SpaRequestHandler')
    names = [node.name for node in handler.body if isinstance(node, ast.FunctionDef)]
    assert sorted(names) == sorted(set(names))
    assert names.count('do_GET') == 1
    assert names.count('do_POST') == 1


def test_get_runs_returns_the_run_list(server: str) -> None:
    status, body = fetch(f'{server}/api/runs')
    assert status == 200
    assert json.loads(body)['runs'] == []


def test_post_runs_reaches_the_adapter(server: str) -> None:
    with patch.object(web.SpaRequestHandler.runs, 'start', return_value={'run_id': 'web-test', 'status': 'running'}) as start:
        status, body = fetch(f'{server}/api/runs', {'constraints': {}, 'budget': 10})
    assert status not in (404, 405)
    assert status == 202
    assert json.loads(body)['run_id'] == 'web-test'
    start.assert_called_once()


def test_unknown_post_is_json_not_method_not_allowed(server: str) -> None:
    status, body = fetch(f'{server}/api/nowhere', {'anything': True})
    assert status == 404
    assert 'error' in json.loads(body)


def test_jarvis_path_goes_to_the_proxy(server: str) -> None:
    def reply(handler: Any) -> None:
        handler._json(200, {'ok': True})

    with patch('backend.presentation.cli.web.forward', side_effect=reply) as forward:
        status, body = fetch(f'{server}/api/jarvis/health')
    assert status == 200
    assert json.loads(body) == {'ok': True}
    forward.assert_called_once()


def test_unknown_spa_route_falls_back_to_index(server: str) -> None:
    status, body = fetch(f'{server}/some/spa/route')
    assert status == 200
    assert b'<title>aios</title>' in body
