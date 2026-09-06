import { useEffect, useState } from 'react';
import type { ConstraintsDoc } from '../../api/types';

type Run = {
  run_id: string; status: string; mode: string; message: string; budget: number;
  evaluations?: number; feasible_evaluations?: number; rejection_reasons?: string[];
  manifest?: { predicted_npv: number | null; verified_npv: number | null; sound: boolean | null };
  validation?: { dynamic_violations: number; failed_identities: string[] };
};
const money = (value: number | null | undefined) => value == null ? 'Ещё не рассчитан' : `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value)} ₽`;

export const LiveRuns = ({ document, blocked }: { document: ConstraintsDoc; blocked: boolean }) => {
  const [runs, setRuns] = useState<Run[]>([]);
  const [budget, setBudget] = useState(30);
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch('/api/runs');
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (!Array.isArray(data.runs)) throw new Error();
        if (active) { setRuns(data.runs); setAvailable(true); }
      } catch { if (active) setAvailable(false); }
    };
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  const busy = sending || runs.some((run) => run.status === 'running');
  const start = async (runId?: string) => {
    setSending(true); setError('');
    try {
      const response = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(runId ? { mode: 'verify', run_id: runId } : { mode: 'search', constraints: document, budget }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Не удалось запустить расчёт.');
      setRuns((current) => [result, ...current.filter((run) => run.run_id !== result.run_id)]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Сервер расчётов недоступен.'); }
    finally { setSending(false); }
  };
  return <section className="live-runs-panel" aria-label="Запуск и результаты">
    <h3 className="scenarios-heading">Запуск и результаты</h3>
    <p className="scenarios-note">Суррогат ищет план по условиям формы. Затем проверьте найденный план в OPM: для сдачи нужен ЧДД полного расчёта и отсутствие нарушений. Скачивать файл для запуска не требуется.</p>
    <label>Глубина поиска <select className="scenarios-input" value={budget} onChange={(event) => setBudget(Number(event.target.value))} disabled={busy}>
      <option value={10}>Пробный поиск — 10 оценок</option><option value={30}>Обычный поиск — 30 оценок</option><option value={120}>Расширенный поиск — 120 оценок</option>
    </select></label>
    <button className="scenarios-button scenarios-button-primary" disabled={blocked || busy || !available} onClick={() => void start()}>Найти план суррогатом</button>
    {!available && <p role="status">Сервер расчётов недоступен. Форма доступна для подготовки условий.</p>}
    {error && <p role="alert" className="scenarios-banner scenarios-banner-error">{error}</p>}
    {runs.length === 0 && <p className="scenarios-note">Новых прогонов пока нет. После запуска результат появится здесь автоматически.</p>}
    {runs.map((run) => <article className="live-runs-panel" key={run.run_id}>
      <h4>Прогон {run.run_id.replace('web-', '')}</h4>
      <p role="status">{run.message}</p>
      <dl><dt>ЧДД — прогноз суррогата</dt><dd>{money(run.manifest?.predicted_npv)}</dd>
        <dt>ЧДД — полный расчёт OPM</dt><dd>{money(run.manifest?.verified_npv)}</dd></dl>
      {run.manifest?.verified_npv != null && run.manifest.predicted_npv != null && <p>Расхождение прогноза: {new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(100 * Math.abs(run.manifest.predicted_npv - run.manifest.verified_npv) / Math.max(1, Math.abs(run.manifest.verified_npv)))}%</p>}
      {run.evaluations != null && <p>Оценено планов: {run.evaluations}. Допустимых на этапе поиска: {run.feasible_evaluations}.</p>}
      {run.validation && <p>Нарушений ограничений: {run.validation.dynamic_violations}. Невыполненных контрольных равенств: {run.validation.failed_identities.length}.</p>}
      {run.rejection_reasons && run.rejection_reasons.length > 0 && <details><summary>Почему отклонялись варианты</summary><ul>{run.rejection_reasons.map((reason) => <li key={reason}>{reason.replaceAll('ood_score', 'отклонение от области обучения').replaceAll('OOD', 'область обучения')}</li>)}</ul></details>}
      {run.manifest && <button className="scenarios-button" disabled={busy} onClick={() => void start(run.run_id)}>Проверить план в OPM</button>}
      <p className="scenarios-note">Проверка использует план и условия, сохранённые при запуске этого прогона. Изменения формы создают новый расчёт.</p>
    </article>)}
  </section>;
};
