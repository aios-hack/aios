import { useId } from 'react';
import { bandGeometry, buildSparkline } from './series';
import './Sparkline.css';

interface SparklineProps {
  values: readonly (number | null | undefined)[];
  current: number;
  label: string;
  total?: number;
  height?: number;
  stroke?: string;
  band?: { min: number; max: number } | null;
}

const VIEW_WIDTH = 100;

export const Sparkline = ({
  values,
  current,
  label,
  total,
  height = 24,
  stroke = 'var(--color-accent)',
  band = null
}: SparklineProps) => {
  const titleId = useId();
  const framed = (baseline: number | null) =>
    buildSparkline(values, { width: VIEW_WIDTH, height, current, total, baseline });
  const geometry =
    band === null
      ? framed(null)
      : (() => {
          const low = framed(band.min);
          const high = framed(band.max);
          return low.max - low.min >= high.max - high.min ? low : high;
        })();
  const corridor = band === null ? null : bandGeometry(geometry, band.min, band.max);

  if (geometry.segments.length === 0) {
    return (
      <svg
        className="sparkline"
        viewBox={`0 0 ${VIEW_WIDTH} ${height}`}
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-labelledby={titleId}
      >
        <title id={titleId}>{label}</title>
      </svg>
    );
  }

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${VIEW_WIDTH} ${height}`}
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-labelledby={titleId}
    >
      <title id={titleId}>{label}</title>
      {corridor !== null && (
        <rect
          className="sparkline-band"
          x={0}
          y={corridor.y}
          width={VIEW_WIDTH}
          height={corridor.height}
        />
      )}
      {geometry.segments.map((segment, index) => (
        <polyline
          key={`${index}:${segment.slice(0, 16)}`}
          className="sparkline-line"
          points={segment}
          stroke={stroke}
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {geometry.marker !== null && (
        <circle
          className="sparkline-marker"
          cx={geometry.marker.x}
          cy={geometry.marker.y}
          r={1.6}
          fill={stroke}
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
  );
};
