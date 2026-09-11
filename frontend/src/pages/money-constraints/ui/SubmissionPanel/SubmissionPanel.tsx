import { useFallbackI18n } from '@/shared/i18n/I18nContext';
import type { RunSubmission } from '@/entities/runs/model/runTypes';
import { ProvenanceRows } from '@/pages/money-constraints/ui/ProvenanceRows';
import { BUNDLE_FIELDS } from '@/pages/money-constraints/model/runFields';
import { formatMoney } from '@/pages/money-constraints/model/runMoney';

interface SubmissionPanelProps {
  submission: RunSubmission | undefined;
  status: string | undefined;
}

export const SubmissionPanel = ({ submission, status }: SubmissionPanelProps) => {
  const { lang, t } = useFallbackI18n();

  if (submission === undefined) {
    return (
      <section className="run-submission" aria-label={t('runs.submissionLabel')}>
        <h5>{t('runs.submissionHeading')}</h5>
        <p className="run-provenance-absent">{t('runs.submissionMissing')}</p>
      </section>
    );
  }

  const claimed = formatMoney(lang, submission.claimed_npv_rub);
  const checkState =
    status === 'verified'
      ? t('runs.checkVerified')
      : status === 'ready_to_submit'
        ? t('runs.checkReady')
        : null;

  return (
    <section className="run-submission" aria-label={t('runs.submissionLabel')}>
      <h5>{t('runs.submissionHeading')}</h5>
      <p className="scenarios-banner scenarios-banner-ok">
        {submission.schedule_present === false
          ? t('runs.submissionBuiltNoSchedule')
          : t('runs.submissionBuilt')}
      </p>
      <dl className="run-provenance-list">
        <div className="run-provenance-row">
          <dt>{t('runs.claimedNpv')}</dt>
          <dd>
            {claimed === null ? (
              <span className="run-provenance-absent">{t('runs.notRecorded')}</span>
            ) : (
              claimed
            )}
          </dd>
        </div>
        <div className="run-provenance-row">
          <dt>{t('runs.checkState')}</dt>
          <dd>
            {checkState === null ? (
              <span className="run-provenance-absent">{t('runs.notRecorded')}</span>
            ) : (
              checkState
            )}
          </dd>
        </div>
      </dl>
      <ProvenanceRows
        fields={BUNDLE_FIELDS}
        source={submission as unknown as Record<string, unknown>}
        lang={lang}
        t={t}
      />
    </section>
  );
};
