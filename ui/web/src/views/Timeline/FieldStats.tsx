import type { TimelineFieldStats } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent } from './format';

interface FieldStatsProps {
  field: TimelineFieldStats;
}

export const FieldStats = ({ field }: FieldStatsProps) => {
  const { t, lang } = useI18n();
  const items = [
    {
      key: 'production',
      label: t('steps.field.production'),
      value: field.production === null ? DASH : formatNumber(lang, field.production)
    },
    {
      key: 'injection',
      label: t('steps.field.injection'),
      value: field.injection === null ? DASH : formatNumber(lang, field.injection)
    },
    {
      key: 'compensation',
      label: t('steps.field.compensation'),
      value: field.compensation === null ? DASH : formatPercent(lang, field.compensation)
    },
    {
      key: 'npv',
      label: t('steps.field.npv'),
      value: formatNumber(lang, field.npv_cumulative)
    },
    {
      key: 'activeWells',
      label: t('steps.field.activeWells'),
      value: formatNumber(lang, field.active_wells)
    }
  ];

  return (
    <dl className="timeline-stats">
      {items.map((item) => (
        <div key={item.key} className="timeline-stat">
          <dt className="timeline-stat-label">{item.label}</dt>
          <dd className="timeline-stat-value" data-stat={item.key}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
};
