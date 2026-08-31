import { memo, useId, useMemo } from 'react';
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

const SparklineView = ({
  values,
  current,
  label,
  total,
  height = 24,
  stroke = 'var(--color-accent)',
  band = null
}: SparklineProps) => {
  const titleId = useId();
  const bandMin = band === null ? null : band.min;
  const bandMax = band === null ? null : band.max;
  const geometry = useMemo(() => {
    const framed = (baseline: number | null) =>
      buildSparkline(values, { width: VIEW_WIDTH, height, current, total, baseline });
    if (bandMin === null || bandMax === null) {
      return framed(null);
    }
    const low = framed(bandMin);
    const high = framed(bandMax);
    return low.max - low.min >= high.max - high.min ? low : high;
  }, [values, height, current, total, bandMin, bandMax]);
  const corridor = useMemo(
    () =>
      bandMin === null || bandMax === null
        ? null
        : bandGeometry(geometry, bandMin, bandMax),
    [geometry, bandMin, bandMax]
  );

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

export const Sparkline = memo(SparklineView);
