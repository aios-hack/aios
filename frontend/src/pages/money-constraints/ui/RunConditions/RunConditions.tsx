import type { Translate } from '@/shared/i18n/I18nContext';
import type { ConstraintsDoc } from '@/entities/scenarios/types';
import { YEAR_SECTIONS } from '@/pages/money-constraints/constraints';

interface RunConditionsProps {
  constraints: ConstraintsDoc;
  t: Translate;
  onLoadConditions?: (document: ConstraintsDoc) => void;
}

export const RunConditions = ({ constraints, t, onLoadConditions }: RunConditionsProps) => {
  const outages = constraints.well_outages
    .map((outage) =>
      t('runs.outageItem', {
        well: outage.well,
        from: outage.control_step_from,
        to: outage.control_step_to
      })
    )
    .join('; ');

  return (
    <details>
      <summary>{t('runs.conditions')}</summary>
      {YEAR_SECTIONS.map((section) => {
        const entries = Object.entries(constraints[section])
          .map(([year, value]) => `${year}: ${value}`)
          .join('; ');
        return (
          <p key={section}>
            {t(`scenarios.section.${section}`)}:{' '}
            {entries === '' ? t('runs.conditionsNone') : entries}.{' '}
            {t(`scenarios.unit.${section}`)}
          </p>
        );
      })}
      <p>
        {t('runs.outages', { list: outages === '' ? t('runs.conditionsNone') : outages })}
      </p>
      {Object.entries(constraints.infrastructure).map(([key, value]) => (
        <p key={key}>
          {t(`scenarios.parameter.${key}.label`)}:{' '}
          {typeof value === 'number' ? value : t(`scenarios.parameter.${value}`)}
        </p>
      ))}
      {onLoadConditions !== undefined && (
        <button
          className="scenarios-button"
          onClick={() => onLoadConditions(constraints)}
          type="button"
        >
          {t('runs.reloadConditions')}
        </button>
      )}
    </details>
  );
};
