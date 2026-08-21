export interface SparkPoint {
  index: number;
  value: number;
}

export interface SparkGeometry {
  segments: string[];
  marker: { x: number; y: number } | null;
  min: number;
  max: number;
  width: number;
  height: number;
}

export interface SparkBand {
  y: number;
  height: number;
}

const finite = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export const collectPoints = (values: readonly (number | null | undefined)[]): SparkPoint[] => {
  const points: SparkPoint[] = [];
  values.forEach((value, index) => {
    if (finite(value)) {
      points.push({ index, value });
    }
  });
  return points;
};

const extent = (points: readonly SparkPoint[], floor: number | null): [number, number] => {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const point of points) {
    min = Math.min(min, point.value);
    max = Math.max(max, point.value);
  }
  if (floor !== null) {
    min = Math.min(min, floor);
    max = Math.max(max, floor);
  }
  if (min === max) {
    return [min - 0.5, max + 0.5];
  }
  return [min, max];
};

export const buildSparkline = (
  values: readonly (number | null | undefined)[],
  options: {
    width: number;
    height: number;
    current: number;
    total?: number;
    baseline?: number | null;
  }
): SparkGeometry => {
  const { width, height, current } = options;
  const total = options.total ?? values.length;
  const points = collectPoints(values);
  const [min, max] = extent(points, options.baseline ?? null);
  const span = max - min;
  const lastIndex = Math.max(total - 1, 1);
  const toX = (index: number): number => (index / lastIndex) * width;
  const toY = (value: number): number => height - ((value - min) / span) * height;

  const segments: string[] = [];
  let run: string[] = [];
  let cursor = -1;
  for (const point of points) {
    if (cursor >= 0 && point.index !== cursor + 1 && run.length > 0) {
      segments.push(run.join(' '));
      run = [];
    }
    run.push(`${toX(point.index).toFixed(2)},${toY(point.value).toFixed(2)}`);
    cursor = point.index;
  }
  if (run.length > 0) {
    segments.push(run.join(' '));
  }

  const currentPoint = points.find((point) => point.index === current) ?? null;
  return {
    segments,
    marker:
      currentPoint === null
        ? null
        : { x: toX(currentPoint.index), y: toY(currentPoint.value) },
    min,
    max,
    width,
    height
  };
};

export const bandGeometry = (
  geometry: SparkGeometry,
  low: number,
  high: number
): SparkBand | null => {
  const span = geometry.max - geometry.min;
  if (span <= 0 || high <= low) {
    return null;
  }
  const toY = (value: number): number =>
    geometry.height - ((value - geometry.min) / span) * geometry.height;
  const top = toY(Math.max(high, low));
  const bottom = toY(Math.min(high, low));
  const clampedTop = Math.max(0, Math.min(geometry.height, top));
  const clampedBottom = Math.max(0, Math.min(geometry.height, bottom));
  if (clampedBottom <= clampedTop) {
    return null;
  }
  return { y: clampedTop, height: clampedBottom - clampedTop };
};
