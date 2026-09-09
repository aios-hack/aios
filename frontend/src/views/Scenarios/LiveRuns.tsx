import { useEffect, useState } from 'react';
import { useFallbackT } from '../../i18n/I18nContext';
import { YEAR_SECTIONS } from './constraints';
import { RunProvenanceDetails, RunProvenanceNotice, SubmissionPanel } from './RunProvenance';
import type { RunManifest, RunSubmission } from './runTypes';
import type { ConstraintsDoc } from '../../api/types';

type Run = {
  run_id: string; status: string; mode: string; message: string; budget: number;
  evaluations?: number; feasible_evaluations?: number; rejection_reasons?: string[];
  manifest?: RunManifest;
  submission?: RunSubmission;
  flow_seconds?: number | null;
  unseen_result?: {
    focus_year: string; fitted_schedule_hashes_count: number; exact_fit_overlap: boolean;
    yearly: Record<string, Record<string, { absolute_error_pct: number | null }>>;
    paired_comparison?: { predicted_npv_change_rub: number; opm_npv_change_rub: number };
  };
  constraints?: ConstraintsDoc;
  progress?: { step: number; total: number; date: string };
  economics?: { measured_npv?: number | null; sound?: boolean };
  provenance?: Partial<RunManifest>;
  validation?: { dynamic_violations: number; blocking_dynamic_violations?: number; failed_identities: string[] };
};
const money = (value: number | null | undefined) => value == null ? 'Ещё не рассчитан' : `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value)} ₽`;

const percent = (value: number | null | undefined) => value == null ? 'не измерено' : `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)}%`;

const provenanceOf = (run: Run): RunManifest | undefined => {
  if (!run.manifest && !run.provenance) return undefined;
  const merged: Record<string, unknown> = { ...run.provenance };
  for (const [key, value] of Object.entries(run.manifest ?? {})) if (value != null) merged[key] = value;
  return merged as RunManifest;
};

export const LiveRuns = ({ document, blocked, onLoadConditions }: { document: ConstraintsDoc; blocked: boolean; onLoadConditions?: (document: ConstraintsDoc) => void }) => {
  const t = useFallbackT();
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
      setRuns((current) => [{ ...current.find((run) => run.run_id === result.run_id), ...result }, ...current.filter((run) => run.run_id !== result.run_id)]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Сервер расчётов недоступен.'); }
    finally { setSending(false); }
  };
  return <section className="live-runs-panel" aria-label="Запуск и результаты">
    <h3 className="scenarios-heading">Запуск и результаты</h3>
    <p className="scenarios-note">Суррогат ищет план по условиям формы. Затем проверьте найденный план в OPM: для сдачи нужен ЧДД полного расчёта и отсутствие нарушений. Скачивать файл для запуска не требуется.</p>
    <p className="scenarios-note">Если политика не найдёт допустимого плана, проверим ещё столько же небольших изменений исходного плана. Все ограничения и проверки доверия сохраняются.</p>
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
      {run.progress && <div><p>Шаг полного расчёта: {run.progress.step} из {run.progress.total}. Дата модели: {run.progress.date}.</p><progress aria-label="Ход расчёта OPM" value={run.progress.step} max={run.progress.total} /></div>}
      <RunProvenanceNotice manifest={provenanceOf(run)} />
      {provenanceOf(run)?.selected_candidate === 'baseline' && <p className="scenarios-note">Среди проверенных допустимых вариантов улучшение исходного плана не найдено.</p>}
      <dl><dt>ЧДД — прогноз суррогата</dt><dd>{money(run.manifest?.predicted_npv)}</dd>
        <dt>ЧДД — полный расчёт OPM</dt><dd>{money(run.economics?.measured_npv ?? run.manifest?.verified_npv)}</dd></dl>
      {run.manifest?.verified_npv != null && run.manifest.predicted_npv != null && <p>Расхождение прогноза: {new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(100 * Math.abs(run.manifest.predicted_npv - run.manifest.verified_npv) / Math.max(1, Math.abs(run.manifest.verified_npv)))}%</p>}
      {run.manifest?.sound === false && <p className="scenarios-banner scenarios-banner-error">План не прошёл полную проверку. Рассчитанный ЧДД нельзя заявлять как подтверждённый.</p>}
      {run.evaluations != null && <p>Оценено планов: {run.evaluations}. Допустимых на этапе поиска: {run.feasible_evaluations}.</p>}
      {run.validation && <p>Блокирующих нарушений: {run.validation.blocking_dynamic_violations ?? (run.manifest?.sound ? 0 : run.validation.dynamic_violations)}. Диагностических замечаний всего: {run.validation.dynamic_violations}. Невыполненных контрольных равенств: {run.validation.failed_identities.length}.</p>}
      {run.rejection_reasons && run.rejection_reasons.length > 0 && <details><summary>Почему отклонялись варианты</summary><ul>{run.rejection_reasons.map((reason) => <li key={reason}>{reason.replaceAll('ood_score', 'отклонение от области обучения').replaceAll('OOD', 'область обучения')}</li>)}</ul></details>}
      {run.manifest && <button className="scenarios-button" disabled={busy} onClick={() => void start(run.run_id)}>Проверить план в OPM</button>}
      {run.unseen_result && <section aria-label="Проверка нового кейса">
        <h4>Проверка нового кейса</h4>
        {!run.unseen_result.exact_fit_overlap && <p>Точного повтора этого плана нет среди {run.unseen_result.fitted_schedule_hashes_count} обучающих расписаний.</p>}
        <p>Ошибки прогноза за {run.unseen_result.focus_year} год:</p>
        <ul>{[['oil_mass_delta', 'Нефть'], ['liquid_volume_delta', 'Жидкость'], ['injection_volume_delta', 'Закачка']].map(([key, label]) => <li key={key}>{label}: {percent(run.unseen_result!.yearly[run.unseen_result!.focus_year][key].absolute_error_pct)}</li>)}</ul>
        {run.unseen_result.paired_comparison && <p>Изменение ЧДД к предыдущему проверенному плану: прогноз {money(run.unseen_result.paired_comparison.predicted_npv_change_rub)}, OPM {money(run.unseen_result.paired_comparison.opm_npv_change_rub)}.</p>}
        <p className="scenarios-note">Малая ошибка общего ЧДД не гарантирует точной оценки небольшого улучшения или потери. Подтверждение OPM относится к выполнению условий выбранным планом, а не к его оптимальности.</p>
      </section>}
      {run.constraints && <details><summary>Условия этого прогона</summary>
        {YEAR_SECTIONS.map((section) => <p key={section}>{t(`scenarios.section.${section}`)}: {Object.entries(run.constraints![section]).map(([year, value]) => `${year}: ${value}`).join('; ') || 'не заданы'}. {t(`scenarios.unit.${section}`)}</p>)}
        <p>Простои: {run.constraints.well_outages.map((outage) => `скважина ${outage.well}, шаги ${outage.control_step_from}–${outage.control_step_to}`).join('; ') || 'не заданы'}</p>
        {Object.entries(run.constraints.infrastructure).map(([key, value]) => <p key={key}>{t(`scenarios.parameter.${key}.label`)}: {typeof value === 'number' ? value : t(`scenarios.parameter.${value}`)}</p>)}
        {onLoadConditions && <button className="scenarios-button" onClick={() => onLoadConditions(run.constraints!)}>Вернуть эти условия в форму</button>}
      </details>}
      <RunProvenanceDetails manifest={provenanceOf(run)} flowSeconds={run.flow_seconds ?? null} />
      <SubmissionPanel submission={run.submission} status={run.manifest?.status ?? run.status} />
      <p className="scenarios-note">Проверка использует план и условия, сохранённые при запуске этого прогона. Изменения формы создают новый расчёт.</p>
    </article>)}
  </section>;
};
