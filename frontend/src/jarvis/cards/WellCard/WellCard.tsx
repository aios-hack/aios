import { Sparkline } from '@/shared/ui/Sparkline';
import { DASH, formatNumber, formatPercent } from '@/shared/lib/format';
import { useI18n } from '@/shared/i18n/I18nContext';
import { readWell } from '@/jarvis/cards/payloads';
import { EmptyPayload } from '@/jarvis/cards/EmptyPayload/EmptyPayload';
import './WellCard.css';

export const WellCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const well = readWell(payload);
  if (well === null) {
    return <EmptyPayload />;
  }
  const values = well.spark.map((point) => point.value);
  const rows: { key: string; label: string; value: string }[] = [
    { key: 'role', label: t('jarvis-cards.wellRole'), value: well.role },
    { key: 'status', label: t('jarvis-cards.wellStatus'), value: well.operating_status },
    {
      key: 'liquid',
      label: t('jarvis-cards.wellLiquid'),
      value: formatNumber(lang, well.liquid_rate, 1)
    },
    {
      key: 'injection',
      label: t('jarvis-cards.wellInjection'),
      value: formatNumber(lang, well.injection_rate, 1)
    },
    {
      key: 'watercut',
      label: t('jarvis-cards.wellWatercut'),
      value: well.watercut === null ? DASH : formatPercent(lang, well.watercut)
    },
    { key: 'bhp', label: t('jarvis-cards.wellBhp'), value: formatNumber(lang, well.bhp, 1) },
    { key: 'setpoint', label: t('jarvis-cards.wellSetpoint'), value: formatNumber(lang, well.setpoint, 1) },
    {
      key: 'npv',
      label: t('jarvis-cards.wellNpv'),
      value: well.npv === null ? DASH : formatNumber(lang, well.npv)
    }
  ];

  return (
    <div className="jarvis-well">
      <dl className="jarvis-well-rows">
        {rows.map((row) => (
          <div className="jarvis-well-row" key={row.key}>
            <dt>{row.label}</dt>
            <dd>{row.value.length === 0 ? DASH : row.value}</dd>
          </div>
        ))}
      </dl>
      {values.length === 0 ? null : (
        <Sparkline
          values={values}
          current={values.length - 1}
          label={t('jarvis-cards.wellLiquid')}
          stroke="var(--color-jarvis-body)"
          height={32}
        />
      )}
    </div>
  );
};
