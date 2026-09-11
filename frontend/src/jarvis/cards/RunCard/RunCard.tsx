import { DASH, formatNumber } from '@/shared/lib/format';
import { useI18n } from '@/shared/i18n/I18nContext';
import { readRun } from '@/jarvis/cards/payloads';
import { EmptyPayload } from '@/jarvis/cards/EmptyPayload/EmptyPayload';
import './RunCard.css';

export const RunCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const run = readRun(payload);
  if (run === null) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-run">
      <p className="jarvis-run-id">{run.run_id}</p>
      <dl className="jarvis-run-facts">
        <div>
          <dt>{t('jarvis-cards.runStatus')}</dt>
          <dd>{run.status ?? DASH}</dd>
        </div>
        <div>
          <dt>{t('jarvis-cards.runPredicted')}</dt>
          <dd>
            {run.predicted_npv === null ? DASH : formatNumber(lang, run.predicted_npv)}
          </dd>
        </div>
        <div>
          <dt>{t('jarvis-cards.runVerified')}</dt>
          <dd>{run.verified_npv === null ? DASH : formatNumber(lang, run.verified_npv)}</dd>
        </div>
        <div>
          <dt>{t('jarvis-cards.compareSound')}</dt>
          <dd>{run.sound === null ? DASH : run.sound ? t('jarvis-cards.yes') : t('jarvis-cards.no')}</dd>
        </div>
        <div>
          <dt>{t('jarvis-cards.runSubmission')}</dt>
          <dd>{run.has_submission ? t('jarvis-cards.yes') : t('jarvis-cards.no')}</dd>
        </div>
      </dl>
      {run.physics === null ? null : (
        <p className="jarvis-run-physics" data-ok={run.physics.admissible === true ? 'true' : 'false'}>
          {t('jarvis-cards.physicsAdmissible')}:{' '}
          {run.physics.admissible === null
            ? DASH
            : run.physics.admissible
              ? t('jarvis-cards.yes')
              : t('jarvis-cards.no')}
          {run.physics.blocking === null
            ? ''
            : ` · ${t('jarvis-cards.physicsBlocking')} ${run.physics.blocking}`}
          {run.physics.warnings === null
            ? ''
            : ` · ${t('jarvis-cards.physicsWarnings')} ${run.physics.warnings}`}
        </p>
      )}
      {run.violations.length === 0 ? null : (
        <ul className="jarvis-run-violations">
          {run.violations.map((row, index) => (
            <li key={`${row.kind}-${index}`}>
              <span className="jarvis-run-violation-kind">{row.kind}</span>
              <span>{row.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {run.schedule_hash === null ? null : (
        <p className="jarvis-run-hash">{run.schedule_hash}</p>
      )}
    </div>
  );
};
