import type { FieldNormBand, TimelineStep } from '../../api/types';

export type FieldMetricKey =
  | 'production'
  | 'injection'
  | 'compensation'
  | 'npv'
  | 'activeWells';

export type MetricTrend = 'up' | 'down' | 'flat';

export type BandPosition = 'below' | 'inside' | 'above';

export interface FieldMetric {
  key: FieldMetricKey;
  values: (number | null)[];
  current: number | null;
  previous: number | null;
  delta: number | null;
  deltaRatio: number | null;
  trend: MetricTrend;
  band: FieldNormBand | null;
  bandPosition: BandPosition | null;
}

const FLAT_RATIO = 0.001;

const readSeries = (
  steps: readonly TimelineStep[],
  read: (step: TimelineStep) => number | null
): (number | null)[] => steps.map(read);

const trendOf = (delta: number | null, previous: number | null): MetricTrend => {
  if (delta === null || previous === null || previous === 0) {
    return 'flat';
  }
  const ratio = Math.abs(delta / previous);
  if (ratio < FLAT_RATIO) {
    return 'flat';
  }
  return delta > 0 ? 'up' : 'down';
};

const positionInBand = (value: number | null, band: FieldNormBand | null): BandPosition | null => {
  if (value === null || band === null) {
    return null;
  }
  if (value < band.min) {
    return 'below';
  }
  if (value > band.max) {
    return 'above';
  }
  return 'inside';
};

const metricOf = (
  key: FieldMetricKey,
  values: (number | null)[],
  stepIndex: number,
  band: FieldNormBand | null
): FieldMetric => {
  const current = values[stepIndex] ?? null;
  const previous = stepIndex > 0 ? values[stepIndex - 1] ?? null : null;
  const delta = current !== null && previous !== null ? current - previous : null;
  const deltaRatio = delta !== null && previous !== null && previous !== 0 ? delta / previous : null;

  return {
    key,
    values,
    current,
    previous,
    delta,
    deltaRatio,
    trend: trendOf(delta, previous),
    band,
    bandPosition: positionInBand(current, band)
  };
};

export const fieldMetrics = (
  steps: readonly TimelineStep[],
  stepIndex: number,
  compensationBand: FieldNormBand | null
): FieldMetric[] => {
  if (steps.length === 0) {
    return [];
  }
  const index = Math.min(Math.max(stepIndex, 0), steps.length - 1);

  return [
    metricOf('production', readSeries(steps, (step) => step.field.production), index, null),
    metricOf('injection', readSeries(steps, (step) => step.field.injection), index, null),
    metricOf(
      'compensation',
      readSeries(steps, (step) => step.field.compensation),
      index,
      compensationBand
    ),
    metricOf('npv', readSeries(steps, (step) => step.field.npv_cumulative), index, null),
    metricOf('activeWells', readSeries(steps, (step) => step.field.active_wells), index, null)
  ];
};
