import { useMemo } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { DASH, formatNumber, formatPercent } from '../../ui/format';
import { overviewMetrics, type OverviewMetric, type OverviewMetricKey } from './overviewMetrics';
import { OverviewCard } from './OverviewCard';
import './Overview.css';

const STROKE: Record<OverviewMetricKey, string> = {
  production: 'var(--color-oil)',
  injection: 'var(--color-injection)',
  compensation: 'var(--color-water)',
  npv: 'var(--color-accent)',
  activeWells: 'var(--color-ok)',
  watercut: 'var(--color-water-pale)',
  factToTarget: 'var(--color-accent-deep)',
  shutWells: 'var(--color-danger)'
};

const FEATURED: readonly OverviewMetricKey[] = ['npv', 'compensation'];

export const Overview = () => {
  const { t, lang } = useI18n();
  const { timeline, stepIndex } = useTimeline();

  const steps = timeline.status === 'ready' ? timeline.data.steps : [];
  const band = timeline.status === 'ready' ? timeline.data.field_norms?.compensation ?? null : null;
  const current = steps.length === 0 ? 0 : Math.min(stepIndex, steps.length - 1);

  const metrics = useMemo(
    () => overviewMetrics(steps, current, band),
    [steps, current, band]
  );

  if (timeline.status === 'loading') {
    return <ViewStatus kind="loading" title={t('app.viewLoading')} />;
  }

  if (timeline.status === 'error') {
    return <ViewStatus kind="error" title={t('app.viewError')} />;
  }

  if (steps.length === 0) {
    return <ViewStatus kind="empty" title={t('overview.empty')} />;
  }

  const formatOf = (metric: OverviewMetric) => (value: number | null) => {
    if (value === null) {
      return DASH;
    }
    if (metric.unit === 'percent') {
      return formatPercent(lang, value);
    }
    return formatNumber(lang, value);
  };

  return (
    <section className="overview" data-testid="overview">
      <p className="overview-lead">{t('overview.lead', { count: steps.length })}</p>
      <div className="overview-grid">
        {metrics.map((metric) => (
          <OverviewCard
            key={metric.key}
            metric={metric}
            steps={steps}
            stepIndex={current}
            stroke={STROKE[metric.key]}
            format={formatOf(metric)}
            featured={FEATURED.includes(metric.key)}
          />
        ))}
      </div>
    </section>
  );
};
