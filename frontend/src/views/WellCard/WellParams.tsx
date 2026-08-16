import type { TimelineWellRow } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent } from '../Timeline/format';

interface WellParamsProps {
  row: TimelineWellRow;
}

export const WellParams = ({ row }: WellParamsProps) => {
  const { t, lang } = useI18n();
  const notCommissioned = row.availability === 'NOT_COMMISSIONED';
  const actual = row.role === 'INJ' ? row.injection_rate : row.liquid_rate;
  const items = [
    { key: 'availability', value: t(`steps.availability.${row.availability}`) },
    { key: 'role', value: notCommissioned ? DASH : t(`steps.role.${row.role}`) },
    {
      key: 'status',
      value: notCommissioned ? DASH : t(`steps.status.${row.operating_status}`)
    },
    {
      key: 'setpoint',
      value: notCommissioned ? DASH : formatNumber(lang, row.setpoint, 1)
    },
    { key: 'actual', value: notCommissioned ? DASH : formatNumber(lang, actual, 1) },
    {
      key: 'factToTarget',
      value: row.fact_to_target === null ? DASH : formatPercent(lang, row.fact_to_target)
    },
    {
      key: 'watercut',
      value:
        notCommissioned || row.watercut === null
          ? DASH
          : formatPercent(lang, row.watercut)
    },
    { key: 'bhp', value: notCommissioned ? DASH : formatNumber(lang, row.bhp, 1) },
    { key: 'cumulative', value: formatNumber(lang, row.cumulative_liquid) }
  ];

  return (
    <dl className="wellcard-params">
      {items.map((item) => (
        <div key={item.key} className="wellcard-param">
          <dt className="wellcard-param-label">{t(`wellcard.params.${item.key}`)}</dt>
          <dd className="wellcard-param-value" data-param={item.key}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
};
