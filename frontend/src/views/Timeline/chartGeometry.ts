export interface ChartPanelGeometry {
  segments: string[];
  min: number;
  max: number;
  top: number;
  height: number;
}

export interface ChartYearTick {
  year: string;
  x: number;
}

const finite = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export const panelGeometry = (
  values: readonly (number | null | undefined)[],
  options: { width: number; top: number; height: number; total: number }
): ChartPanelGeometry => {
  const { width, top, height, total } = options;
  const lastIndex = Math.max(total - 1, 1);
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  values.forEach((value) => {
    if (finite(value)) {
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
  });
  if (min > max) {
    return { segments: [], min: 0, max: 1, top, height };
  }
  if (min === max) {
    min -= 0.5;
    max += 0.5;
  }
  const span = max - min;
  const toX = (index: number): number => (index / lastIndex) * width;
  const toY = (value: number): number => top + height - ((value - min) / span) * height;

  const segments: string[] = [];
  let run: string[] = [];
  let cursor = -1;
  values.forEach((value, index) => {
    if (!finite(value)) {
      return;
    }
    if (cursor >= 0 && index !== cursor + 1 && run.length > 0) {
      segments.push(run.join(' '));
      run = [];
    }
    run.push(`${toX(index).toFixed(2)},${toY(value).toFixed(2)}`);
    cursor = index;
  });
  if (run.length > 0) {
    segments.push(run.join(' '));
  }
  return { segments, min, max, top, height };
};

export const yearTicks = (
  dates: readonly string[],
  options: { width: number; total: number; maxLabels?: number }
): ChartYearTick[] => {
  const lastIndex = Math.max(options.total - 1, 1);
  const ticks: ChartYearTick[] = [];
  let previous = '';
  dates.forEach((date, index) => {
    const year = date.slice(0, 4);
    if (year !== previous) {
      ticks.push({ year, x: (index / lastIndex) * options.width });
      previous = year;
    }
  });
  const maxLabels = options.maxLabels ?? 0;
  if (maxLabels <= 0 || ticks.length <= maxLabels) {
    return ticks;
  }
  const stride = Math.ceil(ticks.length / maxLabels);
  return ticks.filter((_, index) => index % stride === 0);
};

export const indexFromRatio = (ratio: number, total: number): number => {
  const lastIndex = Math.max(total - 1, 0);
  const raw = Math.round(ratio * lastIndex);
  return Math.min(Math.max(raw, 0), lastIndex);
};
