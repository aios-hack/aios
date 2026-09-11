import { memo } from 'react';
import type { FieldNormBand, TimelineStep } from '@/entities/timeline/types';
import { useI18n } from '@/shared/i18n/I18nContext';
import { formatNumber } from '@/shared/lib/format';
import './CompensationPanel.css';

interface CompensationPanelProps {
  step: TimelineStep | undefined;
  band: FieldNormBand | null;
}

type Reading = 'surface' | 'reservoir';

const valueOf = (step: TimelineStep, reading: Reading): number | null => {
  const field = step.field;
  if (reading === 'reservoir') {
    return field.compensation_reservoir ?? null;
  }
  return field.compensation_surface ?? field.compensation ?? null;
};

const statusOf = (value: number | null, band: FieldNormBand | null): string => {
  if (value === null) {
    return 'unrecorded';
  }
  if (band === null) {
    return 'plain';
  }
  return value < band.min || value > band.max ? 'outside' : 'inside';
};

const CompensationReading = ({
  reading,
  value,
  band
}: {
  reading: Reading;
  value: number | null;
  band: FieldNormBand | null;
}) => {
  const { t, lang } = useI18n();
  const status = statusOf(value, band);

  return (
    <div
      className="compensation-reading"
      data-reading={reading}
      data-status={status}
      data-testid={`compensation-${reading}`}
    >
      <span className="compensation-reading-label">
        {t(`steps.compensation.${reading}`)}
      </span>
      <span className="compensation-reading-value">
        {value === null
          ? t('steps.compensation.unrecorded')
          : formatNumber(lang, value, 3)}
      </span>
    </div>
  );
};

const CompensationPanelView = ({ step, band }: CompensationPanelProps) => {
  const { t, lang } = useI18n();

  if (step === undefined) {
    return (
      <section className="compensation-panel" data-testid="compensation-panel">
        <p className="compensation-unrecorded">
          {t('steps.compensation.unrecorded')}
        </p>
      </section>
    );
  }

  const surface = valueOf(step, 'surface');
  const reservoir = valueOf(step, 'reservoir');
  const undefinedDraw = step.field.compensation_defined === false;

  return (
    <section
      className="compensation-panel"
      aria-label={t('steps.compensation.title')}
      data-testid="compensation-panel"
    >
      <header className="compensation-head">
        <h3 className="compensation-title">{t('steps.compensation.title')}</h3>
        {band !== null && (
          <p className="compensation-corridor" data-testid="compensation-corridor">
            <span className="compensation-corridor-range">
              {t('steps.compensation.corridor', {
                min: formatNumber(lang, band.min, 2),
                max: formatNumber(lang, band.max, 2)
              })}
            </span>
            <span
              className="compensation-corridor-source"
              data-source={band.source ?? 'unknown'}
              data-testid="compensation-source"
            >
              {t(
                band.source === 'diagnostic'
                  ? 'steps.compensation.sourceDiagnostic'
                  : 'steps.compensation.sourceUnknown'
              )}
            </span>
          </p>
        )}
      </header>
      <div className="compensation-readings">
        <CompensationReading reading="surface" value={surface} band={band} />
        <CompensationReading reading="reservoir" value={reservoir} band={band} />
      </div>
      {reservoir === null && (
        <p className="compensation-note" data-testid="compensation-surface-note">
          {t('steps.compensation.surfaceOnly')}
        </p>
      )}
      {undefinedDraw && (
        <p className="compensation-note" data-testid="compensation-undefined">
          {t('steps.compensation.undefined')}
        </p>
      )}
      {band?.enforcement === 'diagnostic' && (
        <p className="compensation-note" data-testid="compensation-enforcement">
          {t('steps.compensation.enforcementDiagnostic')}
        </p>
      )}
      {band?.scope !== undefined && (
        <p className="compensation-note" data-testid="compensation-scope">
          {t(`steps.compensation.scope.${band.scope}`)}
        </p>
      )}
    </section>
  );
};

export const CompensationPanel = memo(CompensationPanelView);
