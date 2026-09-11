import { useFallbackI18n } from '@/shared/i18n/I18nContext';
import { formatNumber } from '@/shared/lib/format';
import type { RunManifest } from '@/entities/runs/model/runTypes';
import { ProvenanceRows } from '@/pages/money-constraints/ui/ProvenanceRows';
import {
  HASH_ROWS,
  HOW_FIELDS,
  VERSION_FIELDS
} from '@/pages/money-constraints/model/runFields';

interface RunProvenanceDetailsProps {
  manifest: RunManifest | undefined;
  flowSeconds: number | null;
}

export const RunProvenanceDetails = ({
  manifest,
  flowSeconds
}: RunProvenanceDetailsProps) => {
  const { lang, t } = useFallbackI18n();
  const source = (manifest ?? {}) as unknown as Record<string, unknown>;

  return (
    <details className="run-provenance">
      <summary>{t('runs.provenanceSummary')}</summary>
      {manifest === undefined && (
        <p className="run-provenance-absent">{t('runs.manifestMissing')}</p>
      )}
      <h5>{t('runs.howHeading')}</h5>
      <ProvenanceRows fields={HOW_FIELDS} source={source} lang={lang} t={t} />
      <h5>{t('runs.versionsHeading')}</h5>
      <ProvenanceRows fields={VERSION_FIELDS} source={source} lang={lang} t={t} />
      <h5>{t('runs.hashesHeading')}</h5>
      <p className="scenarios-note">{t('runs.hashesNote')}</p>
      <ProvenanceRows fields={HASH_ROWS} source={source} lang={lang} t={t} />
      <h5>{t('runs.flowHeading')}</h5>
      <dl className="run-provenance-list">
        <div className="run-provenance-row">
          <dt>{t('runs.flowDuration')}</dt>
          <dd>
            {flowSeconds === null ? (
              <span className="run-provenance-absent">{t('runs.notRecorded')}</span>
            ) : (
              t('runs.flowSeconds', { value: formatNumber(lang, flowSeconds, 1) })
            )}
          </dd>
        </div>
      </dl>
    </details>
  );
};
