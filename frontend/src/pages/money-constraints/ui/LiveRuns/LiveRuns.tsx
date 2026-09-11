import { useFallbackI18n } from '@/shared/i18n/I18nContext';
import type { ConstraintsDoc } from '@/entities/scenarios/types';
import { useLiveRuns } from '@/pages/money-constraints/model/useLiveRuns';
import { RunCard } from '@/pages/money-constraints/ui/RunCard';

const DEPTHS = [10, 30, 120] as const;

interface LiveRunsProps {
  document: ConstraintsDoc;
  blocked: boolean;
  onLoadConditions?: (document: ConstraintsDoc) => void;
}

export const LiveRuns = ({ document, blocked, onLoadConditions }: LiveRunsProps) => {
  const { lang, t } = useFallbackI18n();
  const { runs, available, busy, error, budget, setBudget, start } = useLiveRuns({
    document,
    startFailed: t('runs.startFailed'),
    serverDown: t('runs.serverDown')
  });

  return (
    <section className="live-runs-panel" aria-label={t('runs.panelLabel')}>
      <h3 className="scenarios-heading">{t('runs.heading')}</h3>
      <p className="scenarios-note">{t('runs.intro')}</p>
      <p className="scenarios-note">{t('runs.fallbackNote')}</p>
      <label>
        {t('runs.depthLabel')}{' '}
        <select
          className="scenarios-input"
          value={budget}
          onChange={(event) => setBudget(Number(event.target.value))}
          disabled={busy}
        >
          {DEPTHS.map((depth) => (
            <option key={depth} value={depth}>
              {t(`runs.depth.${depth}`)}
            </option>
          ))}
        </select>
      </label>
      <button
        className="scenarios-button scenarios-button-primary"
        disabled={blocked || busy || !available}
        onClick={() => void start()}
        type="button"
      >
        {t('runs.start')}
      </button>
      {!available && <p role="status">{t('runs.unavailable')}</p>}
      {error !== '' && (
        <p role="alert" className="scenarios-banner scenarios-banner-error">
          {error}
        </p>
      )}
      {runs.length === 0 && <p className="scenarios-note">{t('runs.empty')}</p>}
      {runs.map((run) => (
        <RunCard
          key={run.run_id}
          run={run}
          lang={lang}
          t={t}
          busy={busy}
          onVerify={(runId) => void start(runId)}
          onLoadConditions={onLoadConditions}
        />
      ))}
    </section>
  );
};
