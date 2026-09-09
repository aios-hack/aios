from __future__ import annotations
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from backend.domain.configuration.constraints_io import constraints_from_json, constraints_to_json
from backend.core.contracts import water_supply_policy, compensation_policy

PARAMETERS = {'water_supply_unlimited', 'water_reinjection_fraction', 'water_reinjection_lag_steps', 'external_water_m3_per_day', 'water_safety_factor',
              'compensation_min', 'compensation_max', 'compensation_enforcement', 'compensation_scope'}


class WebRuns:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = threading.Lock()

    def recover_interrupted(self):
        for path in self.root.glob('*/job.json'):
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('status') == 'running':
                data.update(status='failed', message='Сервер был перезапущен. Расчёт не подтверждён; запустите его снова.')
                self._write(path.parent, data)

    def _write(self, directory, data):
        temp = directory / 'job.tmp'
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(directory / 'job.json')

    def list(self):
        runs = []
        for path in sorted(self.root.glob('*/job.json'), reverse=True):
            data = json.loads(path.read_text(encoding='utf-8'))
            directory = path.parent
            for name in ('manifest', 'constraints', 'provenance', 'unseen-result'):
                artifact = directory / f'{name}.json'
                if artifact.is_file():
                    data[name.replace('-', '_')] = json.loads(artifact.read_text(encoding='utf-8'))
            validation = directory / 'validation/result.json'
            if validation.is_file():
                data['validation'] = json.loads(validation.read_text(encoding='utf-8'))
            diagnostic = directory / 'diagnostics.json'
            if diagnostic.is_file():
                evaluations = json.loads(diagnostic.read_text(encoding='utf-8')).get('evaluations', [])
                data['evaluations'] = len(evaluations)
                data['feasible_evaluations'] = sum(bool(e['feasible']) for e in evaluations)
                data['rejection_reasons'] = list(dict.fromkeys(
                    v['what'] for e in evaluations for v in e.get('violations', [])))[:5]
            if data.get('status') == 'running' and data.get('mode') == 'verify':
                logs = sorted(directory.glob('opm/runs/*/flow.log'))
                if logs:
                    with logs[-1].open('rb') as stream:
                        stream.seek(0, 2)
                        stream.seek(max(0, stream.tell() - 65536))
                        tail = stream.read().decode('utf-8', errors='replace')
                    steps = re.findall(r'Report step\s+(\d+)/(\d+).*?date = ([^\n]+)', tail)
                    if steps:
                        step, total, date = steps[-1]
                        data['progress'] = {'step': int(step), 'total': int(total), 'date': datetime.strptime(date.strip(), '%d-%b-%Y').strftime('%d.%m.%Y')}
            economics = directory / 'economics/result.json'
            if economics.is_file():
                data['economics'] = json.loads(economics.read_text(encoding='utf-8'))
            runs.append(data)
        return runs[:50]

    def start(self, payload):
        mode = payload.get('mode', 'search')
        if mode not in ('search', 'verify'):
            raise ValueError('Неизвестный вид расчёта.')
        budget = payload.get('budget', 30)
        if type(budget) is not int or budget not in (10, 30, 120):
            raise ValueError('Выберите 10, 30 или 120 оценок.')
        if mode == 'search':
            constraints = constraints_from_json(payload.get('constraints', {}))
            if set(constraints.infrastructure) - PARAMETERS:
                raise ValueError('В условиях есть неподдерживаемый параметр инфраструктуры.')
            water_supply_policy(constraints)
            compensation_policy(constraints)
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('Расчёт уже выполняется. Дождитесь его окончания.')
        try:
            if mode == 'search':
                run_id = datetime.now(timezone.utc).strftime('web-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
                directory = self.root / run_id
                directory.mkdir(parents=True)
                (directory / 'constraints.json').write_text(json.dumps(constraints_to_json(constraints), ensure_ascii=False, indent=2), encoding='utf-8')
                data = {'run_id': run_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'budget': budget}
            else:
                run_id = payload.get('run_id', '')
                if not isinstance(run_id, str) or not run_id.startswith('web-') or Path(run_id).name != run_id:
                    raise ValueError('Некорректный номер прогона.')
                directory = self.root / run_id
                if not (directory / 'manifest.json').is_file() or not (directory / 'constraints.json').is_file():
                    raise ValueError('Сначала найдите план суррогатом.')
                data = json.loads((directory / 'job.json').read_text(encoding='utf-8'))
            data.update(status='running', mode=mode, message='Поиск плана суррогатом…' if mode == 'search' else 'Полный расчёт OPM…')
            self._write(directory, data)
            threading.Thread(target=self._execute, args=(directory, data, mode, budget), daemon=True).start()
            return data
        except BaseException:
            self.lock.release()
            raise

    def _execute(self, directory, data, mode, budget):
        try:
            env = dict(os.environ, OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
            with (directory / f'{mode}.log').open('w', encoding='utf-8') as log:
                result = subprocess.run([sys.executable, '-m', 'backend.presentation.cli.web_run_worker', mode,
                    '--directory', str(directory), '--budget', str(budget)], stdout=log, stderr=subprocess.STDOUT,
                    env=env, timeout=7200, check=False)
            if result.returncode:
                data.update(status='failed', message=('Допустимый план не найден или расчёт завершился ошибкой. См. причины отклонения ниже.'
                    if mode == 'search' else 'Проверка OPM не завершена. Проверьте доступность Docker и образа OPM.'))
            else:
                manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
                data.update(status='completed', message=('Прогноз готов. Для подтверждения запустите OPM.' if mode == 'search'
                    else 'OPM завершён. Все проверки пройдены.' if manifest['sound'] else 'OPM завершён: план не прошёл проверку.'))
        except Exception:
            data.update(status='failed', message='Не удалось завершить расчёт. Подробности сохранены в журнале на сервере.')
        finally:
            self._write(directory, data)
            self.lock.release()
