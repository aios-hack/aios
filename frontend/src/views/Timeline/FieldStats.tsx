import { memo, useMemo } from 'react';
import type { TimelineFieldNorms, TimelineStep } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { Sparkline } from '../../ui/Sparkline';
import { DASH, formatNumber, formatPercent } from '../../ui/format';
import { fieldMetrics, type FieldMetricKey } from './fieldMetrics';
import { MetricChart } from './MetricChart';
import './FieldStats.css';

interface FieldStatsProps {
  steps: TimelineStep[];
  stepIndex: number;
  norms?: TimelineFieldNorms;
  expanded: boolean;
}

const STROKE: Record<FieldMetricKey, string> = {
  production: 'var(--color-oil)',
  injection: 'var(--color-injection)',
  compensation: 'var(--color-water)',
  npv: 'var(--color-accent)',
  activeWells: 'var(--color-ok)'
};

const LABEL: Record<FieldMetricKey, string> = {
  production: 'steps.field.production',
  injection: 'steps.field.injection',
  compensation: 'steps.field.compensation',
  npv: 'steps.field.npv',
  activeWells: 'steps.field.activeWells'
};

const SPARK_HEIGHT = 22;

const FieldStatsView = ({ steps, stepIndex, norms, expanded }: FieldStatsProps) => {
  const { t, lang } = useI18n();
  const band = norms?.compensation ?? null;

  const metrics = useMemo(
    () => fieldMetrics(steps, stepIndex, band),
    [steps, stepIndex, band]
  );

  const formatOf = (key: FieldMetricKey) => (value: number) =>
    key === 'compensation' ? formatPercent(lang, value) : formatNumber(lang, value);

  return (
    <dl className="timeline-stats" data-expanded={expanded ? 'true' : undefined}>
      {metrics.map((metric) => {
        const label = t(LABEL[metric.key]);
        const format = formatOf(metric.key);
        const value = metric.current === null ? DASH : format(metric.current);
        const deltaLabel =
          metric.delta === null || metric.trend === 'flat'
            ? null
            : `${metric.delta > 0 ? '+' : '−'}${format(Math.abs(metric.delta))}`;

        return (
          <div
            className="timeline-stat"
            key={metric.key}
            data-metric={metric.key}
            data-band={metric.bandPosition ?? undefined}
          >
            <dt className="timeline-stat-label">{label}</dt>
            <dd className="timeline-stat-value" data-stat={metric.key}>
              <span className="timeline-stat-number">{value}</span>
              {deltaLabel !== null && (
                <span className="timeline-stat-delta" data-trend={metric.trend}>
                  {deltaLabel}
                </span>
              )}
            </dd>
            {expanded ? (
              <div className="timeline-stat-chart">
                <MetricChart
                  metric={metric}
                  steps={steps}
                  stepIndex={stepIndex}
                  stroke={STROKE[metric.key]}
                  label={t('steps.sparkline', { name: label })}
                  format={format}
                />
              </div>
            ) : (
              <div className="timeline-stat-spark" data-spark={metric.key}>
                <Sparkline
                  values={metric.values}
                  current={stepIndex}
                  total={steps.length}
                  label={t('steps.sparkline', { name: label })}
                  height={SPARK_HEIGHT}
                  stroke={STROKE[metric.key]}
                  band={metric.band}
                />
              </div>
            )}
            {metric.key === 'compensation' && metric.band !== null && (
              <p className="timeline-stat-norm">
                {t('steps.field.compensationBand', {
                  min: formatPercent(lang, metric.band.min),
                  max: formatPercent(lang, metric.band.max)
                })}
              </p>
            )}
          </div>
        );
      })}
    </dl>
  );
};

export const FieldStats = memo(FieldStatsView);
