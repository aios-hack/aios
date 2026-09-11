import type { Translate } from '@/shared/i18n/I18nContext';
import type { Lang } from '@/shared/i18n/dictionaries';
import type { ConstraintsDoc } from '@/entities/scenarios/types';
import {
  blockingViolationsOf,
  provenanceOf,
  type LiveRun
} from '@/pages/money-constraints/model/runTypes';
import { RunConditions } from '@/pages/money-constraints/ui/RunConditions';
import { RunProvenanceDetails } from '@/pages/money-constraints/ui/RunProvenanceDetails';
import { RunProvenanceNotice } from '@/pages/money-constraints/ui/RunProvenanceNotice';
import { SubmissionPanel } from '@/pages/money-constraints/ui/SubmissionPanel';
import { UnseenCheck } from '@/pages/money-constraints/ui/UnseenCheck';
import {
  forecastDrift,
  formatMoney
} from '@/pages/money-constraints/ui/runMoney';
import { formatNumber } from '@/shared/lib/format';

interface RunCardProps {
  run: LiveRun;
  lang: Lang;
  t: Translate;
  busy: boolean;
  onVerify: (runId: string) => void;
  onLoadConditions?: (document: ConstraintsDoc) => void;
}

export const RunCard = ({
  run,
  lang,
  t,
  busy,
  onVerify,
  onLoadConditions
}: RunCardProps) => {
  const provenance = provenanceOf(run);
  const predicted = formatMoney(lang, run.manifest?.predicted_npv);
  const verified = formatMoney(
    lang,
    run.economics?.measured_npv ?? run.manifest?.verified_npv
  );
  const forecast = run.manifest?.predicted_npv;
  const measured = run.manifest?.verified_npv;
  const drift =
    forecast !== null && forecast !== undefined && measured !== null && measured !== undefined
      ? forecastDrift(forecast, measured)
      : null;

  return (
    <article className="live-runs-panel">
      <h4>{t('runs.runTitle', { id: run.run_id.replace('web-', '') })}</h4>
      <p role="status">{run.message}</p>
      {run.progress !== undefined && (
        <div>
          <p>
            {t('runs.progress', {
              step: run.progress.step,
              total: run.progress.total,
              date: run.progress.date
            })}
          </p>
          <progress
            aria-label={t('runs.progressLabel')}
            value={run.progress.step}
            max={run.progress.total}
          />
        </div>
      )}
      <RunProvenanceNotice manifest={provenance} />
      {provenance?.selected_candidate === 'baseline' && (
        <p className="scenarios-note">{t('runs.noImprovement')}</p>
      )}
      <dl>
        <dt>{t('runs.npvPredicted')}</dt>
        <dd>{predicted ?? t('runs.npvPending')}</dd>
        <dt>{t('runs.npvVerified')}</dt>
        <dd>{verified ?? t('runs.npvPending')}</dd>
      </dl>
      {drift !== null && (
        <p>{t('runs.driftLabel', { value: formatNumber(lang, drift, 2) })}</p>
      )}
      {run.manifest?.sound === false && (
        <p className="scenarios-banner scenarios-banner-error">{t('runs.unsound')}</p>
      )}
      {run.evaluations !== undefined && (
        <p>
          {t('runs.evaluations', {
            count: run.evaluations,
            feasible: run.feasible_evaluations ?? 0
          })}
        </p>
      )}
      {run.validation !== undefined && (
        <p>
          {t('runs.violations', {
            blocking: blockingViolationsOf(run),
            total: run.validation.dynamic_violations,
            identities: run.validation.failed_identities.length
          })}
        </p>
      )}
      {run.rejection_reasons !== undefined && run.rejection_reasons.length > 0 && (
        <details>
          <summary>{t('runs.rejections')}</summary>
          <ul>
            {run.rejection_reasons.map((reason) => (
              <li key={reason}>
                {reason
                  .replaceAll('ood_score', t('runs.oodScore'))
                  .replaceAll('OOD', t('runs.oodShort'))}
              </li>
            ))}
          </ul>
        </details>
      )}
      {run.manifest !== undefined && (
        <button
          className="scenarios-button"
          disabled={busy}
          onClick={() => onVerify(run.run_id)}
          type="button"
        >
          {t('runs.verify')}
        </button>
      )}
      {run.unseen_result !== undefined && (
        <UnseenCheck result={run.unseen_result} lang={lang} t={t} />
      )}
      {run.constraints !== undefined && (
        <RunConditions
          constraints={run.constraints}
          t={t}
          onLoadConditions={onLoadConditions}
        />
      )}
      <RunProvenanceDetails manifest={provenance} flowSeconds={run.flow_seconds ?? null} />
      <SubmissionPanel
        submission={run.submission}
        status={run.manifest?.status ?? run.status}
      />
      <p className="scenarios-note">{t('runs.footnote')}</p>
    </article>
  );
};
