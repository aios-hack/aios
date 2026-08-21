import { memo, useMemo } from 'react';
import type { TimelineFieldNorms, TimelineStep } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { Sparkline } from '../../ui/Sparkline';
import { DASH, formatNumber, formatPercent } from '../../ui/format';
import './FieldStats.css';

interface FieldStatsProps {
  steps: TimelineStep[];
  stepIndex: number;
  norms?: TimelineFieldNorms;
}

type StatKey = 'production' | 'injection' | 'compensation' | 'npv' | 'activeWells';

const STROKE: Record<StatKey, string> = {
  production: 'var(--color-oil)',
  injection: 'var(--color-injection)',
  compensation: 'var(--color-water)',
  npv: 'var(--color-accent)',
  activeWells: 'var(--color-text-muted)'
};

const SPARK_HEIGHT = 24;

const FieldStatsView = ({ steps, stepIndex, norms }: FieldStatsProps) => {
  const { t, lang } = useI18n();

  const series = useMemo(
    () => ({
      production: steps.map((step) => step.field.production),
      injection: steps.map((step) => step.field.injection),
      compensation: steps.map((step) => step.field.compensation),
      npv: steps.map((step) => step.field.npv_cumulative),
      activeWells: steps.map((step) => step.field.active_wells)
    }),
    [steps]
  );

  const field = steps[stepIndex].field;
  const band = norms?.compensation ?? null;

  const items: { key: StatKey; label: string; value: string }[] = [
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
          <div className="timeline-stat-spark" data-spark={item.key}>
            <Sparkline
              values={series[item.key]}
              current={stepIndex}
              total={steps.length}
              label={t('steps.sparkline', { name: item.label })}
              height={SPARK_HEIGHT}
              stroke={STROKE[item.key]}
              band={item.key === 'compensation' ? band : null}
            />
          </div>
          {item.key === 'compensation' && band !== null && (
            <p className="timeline-stat-norm">
              {t('steps.field.compensationBand', {
                min: formatPercent(lang, band.min),
                max: formatPercent(lang, band.max)
              })}
            </p>
          )}
        </div>
      ))}
    </dl>
  );
};

export const FieldStats = memo(FieldStatsView);
