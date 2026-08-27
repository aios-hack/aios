import { useId, useMemo } from 'react';
import type { TimelineStep } from '../../api/types';
import { bandGeometry, buildSparkline } from '../../ui/Sparkline/series';
import { yearTicks } from '../../app/events';
import type { FieldMetric } from './fieldMetrics';

interface MetricChartProps {
  metric: FieldMetric;
  steps: readonly TimelineStep[];
  stepIndex: number;
  stroke: string;
  label: string;
  format: (value: number) => string;
}

const VIEW_WIDTH = 100;
const VIEW_HEIGHT = 34;

export const MetricChart = ({
  metric,
  steps,
  stepIndex,
  stroke,
  label,
  format
}: MetricChartProps) => {
  const titleId = useId();

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
    () =>
      metric.band === null ? null : bandGeometry(geometry, metric.band.min, metric.band.max),
    [geometry, metric.band]
  );

  const ticks = useMemo(() => yearTicks([...steps]), [steps]);
  const labelStride = Math.max(1, Math.ceil(ticks.length / 6));
  const labelled = useMemo(
    () => ticks.filter((_, index) => index % labelStride === 0),
    [ticks, labelStride]
  );

  const lastIndex = Math.max(steps.length - 1, 1);

  return (
    <figure className="metric-chart">
      <svg
        className="metric-chart-plot"
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-labelledby={titleId}
      >
        <title id={titleId}>{label}</title>
        {corridor !== null && (
          <rect
            className="metric-chart-band"
            x={0}
            y={corridor.y}
            width={VIEW_WIDTH}
            height={corridor.height}
          />
        )}
        {ticks.map((tick) => (
          <line
            key={tick.year}
            className="metric-chart-grid"
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
            className="metric-chart-line"
            points={segment}
            stroke={stroke}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {geometry.marker !== null && (
          <line
            className="metric-chart-cursor"
            x1={geometry.marker.x}
            x2={geometry.marker.x}
            y1={0}
            y2={VIEW_HEIGHT}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {geometry.marker !== null && (
          <circle
            className="metric-chart-marker"
            cx={geometry.marker.x}
            cy={geometry.marker.y}
            r={1.1}
            fill={stroke}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      <figcaption className="metric-chart-scale">
        <span className="metric-chart-bound">{format(geometry.max)}</span>
        <span className="metric-chart-bound">{format(geometry.min)}</span>
      </figcaption>
      <div className="metric-chart-years" aria-hidden="true">
        {labelled.map((tick) => (
          <span
            key={tick.year}
            className="metric-chart-year"
            style={{ left: `${(tick.step / lastIndex) * 100}%` }}
          >
            {tick.year}
          </span>
        ))}
      </div>
    </figure>
  );
};
