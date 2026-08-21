import type { TimelineWellRow } from '../../api/types';
import { actualRate } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent } from '../../ui/format';

interface WellParamsProps {
  row: TimelineWellRow;
}

export const WellParams = ({ row }: WellParamsProps) => {
  const { t, lang } = useI18n();
  const notCommissioned = row.availability === 'NOT_COMMISSIONED';
  const items = [
    { key: 'availability', value: t(`steps.availability.${row.availability}`), numeric: false },
    {
      key: 'role',
      value: notCommissioned ? DASH : t(`steps.role.${row.role}`),
      numeric: false
    },
    {
      key: 'status',
      value: notCommissioned ? DASH : t(`steps.status.${row.operating_status}`),
      numeric: false
    },
    {
      key: 'setpoint',
      value: notCommissioned ? DASH : formatNumber(lang, row.setpoint, 1),
      numeric: !notCommissioned
    },
    {
      key: 'actual',
      value: notCommissioned ? DASH : formatNumber(lang, actualRate(row), 1),
      numeric: !notCommissioned
    },
    {
      key: 'factToTarget',
      value: row.fact_to_target === null ? DASH : formatPercent(lang, row.fact_to_target),
      numeric: row.fact_to_target !== null
    },
    {
      key: 'watercut',
      value:
        notCommissioned || row.watercut === null
          ? DASH
          : formatPercent(lang, row.watercut),
      numeric: !notCommissioned && row.watercut !== null
    },
    {
      key: 'bhp',
      value: notCommissioned ? DASH : formatNumber(lang, row.bhp, 1),
      numeric: !notCommissioned
    },
    { key: 'cumulative', value: formatNumber(lang, row.cumulative_liquid), numeric: true }
  ];

  return (
    <dl className="wellcard-params">
      {items.map((item) => (
        <div key={item.key} className="wellcard-param">
          <dt className="wellcard-param-label">{t(`wellcard.params.${item.key}`)}</dt>
          <dd
            className="wellcard-param-value"
            data-param={item.key}
            data-numeric={item.numeric}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
};
