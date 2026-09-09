import type { RunManifest, RunSubmission } from './runTypes';

const NOT_RECORDED = 'не записано';

const HASH_FIELDS = new Set([
  'feature_context_sha256', 'constraints_hash', 'deck_hash', 'normatives_sha256', 'git_commit',
  'canonical_schedule_hash', 'content_hash_submission', 'response_hash', 'economics_config_hash',
  'methodology_version_hash', 'schedule_hash'
]);

const FALLBACK_STRATEGIES = new Set(['baseline-neighborhood', 'fallback', 'baseline_neighborhood']);

export const isFallbackStrategy = (strategy: string | null | undefined) =>
  strategy != null && FALLBACK_STRATEGIES.has(strategy);

export const isEquilibriumUnclaimed = (equilibrium: string | null | undefined) =>
  equilibrium != null && (equilibrium === 'not-claimed' || equilibrium === 'not_claimed');

const STRATEGY_LABELS: Record<string, string> = {
  'baseline-neighborhood': 'резервный поиск около исходного плана',
  'baseline_neighborhood': 'резервный поиск около исходного плана',
  'fallback': 'резервный поиск',
  'policy': 'агентная политика',
  'agent-policy': 'агентная политика'
};

const CANDIDATE_LABELS: Record<string, string> = {
  baseline: 'исходный план',
  'local-change': 'небольшое изменение исходного плана'
};

const money = (value: number | null | undefined) => value == null ? NOT_RECORDED
  : `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value)} ₽`;

const Hash = ({ value }: { value: string }) => {
  const head = value.slice(0, 12);
  return head.length < value.length
    ? <abbr className="run-provenance-hash" title={value}>{head}…</abbr>
    : <span className="run-provenance-hash">{value}</span>;
};

const Value = ({ name, value }: { name: string; value: unknown }) => {
  if (value == null || value === '') return <span className="run-provenance-absent">{NOT_RECORDED}</span>;
  if (typeof value === 'boolean') return <>{value ? 'да' : 'нет'}</>;
  if (typeof value === 'number') return <>{new Intl.NumberFormat('ru-RU').format(value)}</>;
  const text = String(value);
  if (HASH_FIELDS.has(name)) return <Hash value={text} />;
  if (name === 'search_strategy') return <>{STRATEGY_LABELS[text] ?? text}</>;
  if (name === 'selected_candidate') return <>{CANDIDATE_LABELS[text] ?? text}</>;
  if (name === 'policy_equilibrium') return <>{isEquilibriumUnclaimed(text) ? 'не заявлено' : text}</>;
  return <>{text}</>;
};

const Rows = ({ fields, source }: { fields: [string, string][]; source: Record<string, unknown> }) =>
  <dl className="run-provenance-list">{fields.map(([name, label]) => <div className="run-provenance-row" key={name}>
    <dt>{label}</dt><dd><Value name={name} value={source[name]} /></dd>
  </div>)}</dl>;

const HOW: [string, string][] = [
  ['search_strategy', 'Способ поиска'], ['selected_candidate', 'Что выбрано'],
  ['policy_equilibrium', 'Равновесие политики'], ['iterations', 'Оценено вариантов'],
  ['self_consistent', 'Самосогласованность'], ['seed', 'Зерно случайности']
];

const VERSIONS: [string, string][] = [
  ['model_version', 'Версия модели'], ['npv_head_version', 'Версия головы ЧДД'],
  ['scenario_ood_version', 'Версия контроля области обучения'], ['opm_image', 'Образ OPM'],
  ['git_commit', 'Коммит кода']
];

const HASHES: [string, string][] = [
  ['schedule_hash', 'Хеш расписания'], ['constraints_hash', 'Хеш условий'],
  ['deck_hash', 'Хеш модели пласта'], ['feature_context_sha256', 'Хеш контекста признаков'],
  ['normatives_sha256', 'Хеш нормативов']
];

export const RunProvenanceNotice = ({ manifest }: { manifest: RunManifest | undefined }) => {
  const fallback = isFallbackStrategy(manifest?.search_strategy);
  const unclaimed = isEquilibriumUnclaimed(manifest?.policy_equilibrium);
  if (!fallback && !unclaimed) return null;
  return <p className="scenarios-banner run-provenance-notice" role="note">
    {fallback
      ? 'План найден резервным поиском около исходного плана, а не агентной политикой.'
      : 'Сходимость агентной политики для этого плана не заявлена.'}
    {' '}Это не ошибка: результат получен допустимым запасным способом, и проверки условий к нему применялись те же. Учитывайте это при сравнении с прогонами основного поиска.
  </p>;
};

export const RunProvenanceDetails = ({ manifest, flowSeconds }: { manifest: RunManifest | undefined; flowSeconds: number | null }) => {
  const source = (manifest ?? {}) as unknown as Record<string, unknown>;
  return <details className="run-provenance">
    <summary>Происхождение результата</summary>
    {!manifest && <p className="run-provenance-absent">Манифест прогона ещё не записан.</p>}
    <h5>Как получен план</h5><Rows fields={HOW} source={source} />
    <h5>Версии и кейс</h5><Rows fields={VERSIONS} source={source} />
    <h5>Хеши</h5>
    <p className="scenarios-note">Показаны первые 12 символов; полное значение — в подсказке при наведении.</p>
    <Rows fields={HASHES} source={source} />
    <h5>Время полного расчёта</h5>
    <dl className="run-provenance-list"><div className="run-provenance-row">
      <dt>Длительность Flow</dt>
      <dd>{flowSeconds == null ? <span className="run-provenance-absent">{NOT_RECORDED}</span>
        : `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(flowSeconds)} с`}</dd>
    </div></dl>
  </details>;
};

const BUNDLE: [string, string][] = [
  ['canonical_schedule_hash', 'Хеш расписания сдачи'], ['content_hash_submission', 'Хеш содержимого пакета'],
  ['response_hash', 'Хеш отклика'], ['deck_hash', 'Хеш модели пласта'],
  ['constraints_hash', 'Хеш условий'], ['economics_config_hash', 'Хеш конфигурации экономики'],
  ['methodology_version_hash', 'Хеш версии методики'], ['opm_image', 'Образ OPM'],
  ['git_commit', 'Коммит кода'], ['source_run_id', 'Прогон-источник'], ['created_at', 'Собран']
];

export const SubmissionPanel = ({ submission, status }: { submission: RunSubmission | undefined; status: string | undefined }) => {
  if (!submission) return <section className="run-submission" aria-label="Пакет сдачи">
    <h5>Пакет сдачи</h5>
    <p className="run-provenance-absent">Пакет сдачи не собран. Заявленный ЧДД и хеши пакета появятся после сборки.</p>
  </section>;
  const verified = status === 'verified';
  return <section className="run-submission" aria-label="Пакет сдачи">
    <h5>Пакет сдачи</h5>
    <p className="scenarios-banner scenarios-banner-ok">Пакет собран{submission.schedule_present === false ? ', но файл расписания отсутствует' : ''}.</p>
    <dl className="run-provenance-list"><div className="run-provenance-row">
      <dt>Заявленный ЧДД</dt><dd>{money(submission.claimed_npv_rub)}</dd>
    </div><div className="run-provenance-row">
      <dt>Состояние проверки</dt>
      <dd>{verified ? 'проверен полным расчётом' : status === 'ready_to_submit' ? 'собран, полная проверка не подтверждена'
        : <span className="run-provenance-absent">не записано</span>}</dd>
    </div></dl>
    <Rows fields={BUNDLE} source={submission as unknown as Record<string, unknown>} />
  </section>;
};
