import { useId, useMemo, type CSSProperties } from 'react';
import type { TimelineStep } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { bandGeometry, buildSparkline } from '../../ui/Sparkline/series';
import { yearTicks } from '../../app/events';
import { DASH } from '../../ui/format';
import type { OverviewMetric, OverviewMetricKey } from './overviewMetrics';

interface OverviewCardProps {
  metric: OverviewMetric;
  steps: readonly TimelineStep[];
  stepIndex: number;
  stroke: string;
  format: (value: number | null) => string;
  featured: boolean;
  ordinal: number;
}

const VIEW_WIDTH = 100;
const VIEW_HEIGHT = 30;
const YEAR_TARGET = 6;

const bandKeyOf = (metric: OverviewMetric): string | null => {
  if (metric.band === null || metric.current === null) {
    return null;
  }
  if (metric.current < metric.band.min) {
    return 'overview.bandBelow';
  }
  if (metric.current > metric.band.max) {
    return 'overview.bandAbove';
  }
  return 'overview.bandInside';
};

const GUIDE_ANCHOR: Partial<Record<OverviewMetricKey, string>> = {
  activeWells: 'overview-active-metric',
  production: 'overview-production-metric',
  injection: 'overview-injection-metric',
  compensation: 'overview-compensation-metric',
  npv: 'overview-npv-metric'
};

export const OverviewCard = ({
  metric,
  steps,
  stepIndex,
  stroke,
  format,
  featured,
  ordinal
}: OverviewCardProps) => {
  const { t } = useI18n();
  const titleId = useId();
  const label = t(`overview.metric.${metric.key}`);
  const unit = t(`overview.unit.${metric.key}`);

  const geometry = useMemo(() => {
    const framed = (baseline: number | null) =>
      buildSparkline(metric.values, {
        width: VIEW_WIDTH,
        height: VIEW_HEIGHT,
        current: stepIndex,
        total: steps.length,
        baseline
      });
    if (metric.band === null) {
      return framed(null);
    }
    const low = framed(metric.band.min);
    const high = framed(metric.band.max);
    return low.max - low.min >= high.max - high.min ? low : high;
  }, [metric.values, metric.band, stepIndex, steps.length]);

  const corridor = useMemo(
    () => (metric.band === null ? null : bandGeometry(geometry, metric.band.min, metric.band.max)),
    [geometry, metric.band]
  );

  const ticks = useMemo(() => yearTicks(steps), [steps]);
  const stride = Math.max(1, Math.ceil(ticks.length / YEAR_TARGET));
  const labelled = ticks.filter((_, index) => index % stride === 0);
  const lastIndex = Math.max(steps.length - 1, 1);
  const bandKey = bandKeyOf(metric);

  const deltaLabel =
    metric.delta === null || metric.delta === 0
      ? null
      : `${metric.delta > 0 ? '+' : '−'}${format(Math.abs(metric.delta))}`;

  return (
    <article
      className="overview-card"
      data-metric={metric.key}
      data-guide={GUIDE_ANCHOR[metric.key]}
      data-featured={featured ? 'true' : undefined}
      data-band={bandKey === null ? undefined : bandKey.split('.').pop()}
      data-ordinal={ordinal}
      style={{ '--overview-card-index': ordinal } as CSSProperties}
    >
      <header className="overview-card-head">
        <h3 className="overview-card-title">{label}</h3>
        <p className="overview-card-reading">
          <span className="overview-card-value">{format(metric.current)}</span>
          <span className="overview-card-unit">{unit}</span>
          {deltaLabel !== null && (
            <span className="overview-card-delta" data-trend={metric.delta! > 0 ? 'up' : 'down'}>
              {deltaLabel}
            </span>
          )}
        </p>
      </header>

      <svg
        className="overview-card-plot"
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-labelledby={titleId}
      >
        <title id={titleId}>{`${label}, ${unit}`}</title>
        {corridor !== null && (
          <rect
            className="overview-card-band"
            x={0}
            y={corridor.y}
            width={VIEW_WIDTH}
            height={corridor.height}
          />
        )}
        {labelled.map((tick) => (
          <line
            key={tick.year}
            className="overview-card-grid"
            x1={(tick.step / lastIndex) * VIEW_WIDTH}
            x2={(tick.step / lastIndex) * VIEW_WIDTH}
            y1={0}
            y2={VIEW_HEIGHT}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {geometry.segments.map((segment, index) => (
          <polyline
            key={`${index}:${segment.slice(0, 16)}`}
            className="overview-card-line"
            points={segment}
            stroke={stroke}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {geometry.marker !== null && (
          <line
            className="overview-card-cursor"
            x1={geometry.marker.x}
            x2={geometry.marker.x}
            y1={0}
            y2={VIEW_HEIGHT}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {geometry.marker !== null && (
          <circle
            className="overview-card-marker"
            cx={geometry.marker.x}
            cy={geometry.marker.y}
            r={featured ? 0.9 : 1.2}
            fill={stroke}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      <div className="overview-card-years" aria-hidden="true">
        {labelled.map((tick) => (
          <span
            key={tick.year}
            className="overview-card-year"
            style={{ left: `${(tick.step / lastIndex) * 100}%` }}
          >
            {tick.year}
          </span>
        ))}
      </div>

      <footer className="overview-card-foot">
        <span className="overview-card-span">
          {t('overview.span', {
            from: metric.first === null ? DASH : format(metric.first),
            to: metric.last === null ? DASH : format(metric.last),
            unit
          })}
        </span>
        {bandKey !== null && <span className="overview-card-flag">{t(bandKey)}</span>}
      </footer>
    </article>
  );
};
