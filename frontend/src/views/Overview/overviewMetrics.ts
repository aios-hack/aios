import type { FieldNormBand, TimelineStep, TimelineWellRow } from '../../api/types';

export type OverviewMetricKey =
  | 'production'
  | 'injection'
  | 'compensation'
  | 'npv'
  | 'activeWells'
  | 'watercut'
  | 'factToTarget'
  | 'shutWells';

export type MetricUnit = 'volume' | 'percent' | 'count' | 'money';

export interface OverviewMetric {
  key: OverviewMetricKey;
  unit: MetricUnit;
  values: (number | null)[];
  current: number | null;
  previous: number | null;
  delta: number | null;
  band: FieldNormBand | null;
  first: number | null;
  last: number | null;
  peak: number | null;
  trough: number | null;
}

const mean = (values: number[]): number | null =>
  values.length === 0 ? null : values.reduce((sum, value) => sum + value, 0) / values.length;

const producersOf = (rows: readonly TimelineWellRow[]): TimelineWellRow[] =>
  rows.filter((row) => row.role === 'PROD');

export const averageWatercut = (step: TimelineStep): number | null =>
  mean(
    producersOf(step.wells)
      .map((row) => row.watercut)
      .filter((value): value is number => value !== null)
  );

export const averageFactToTarget = (step: TimelineStep): number | null =>
  mean(
    step.wells
      .map((row) => row.fact_to_target)
      .filter((value): value is number => value !== null)
  );

export const shutWellCount = (step: TimelineStep): number =>
  step.wells.filter((row) => row.operating_status === 'SHUT').length;

const finiteOf = (values: readonly (number | null)[]): number[] =>
  values.filter((value): value is number => value !== null && Number.isFinite(value));

const buildMetric = (
  key: OverviewMetricKey,
  unit: MetricUnit,
  values: (number | null)[],
  stepIndex: number,
  band: FieldNormBand | null
): OverviewMetric => {
  const finite = finiteOf(values);
  const current = values[stepIndex] ?? null;
  const previous = stepIndex > 0 ? values[stepIndex - 1] ?? null : null;

  return {
    key,
    unit,
    values,
    current,
    previous,
    delta: current !== null && previous !== null ? current - previous : null,
    band,
    first: finite.length > 0 ? finite[0] : null,
    last: finite.length > 0 ? finite[finite.length - 1] : null,
    peak: finite.length > 0 ? Math.max(...finite) : null,
    trough: finite.length > 0 ? Math.min(...finite) : null
  };
};

export const overviewMetrics = (
  steps: readonly TimelineStep[],
  stepIndex: number,
  compensationBand: FieldNormBand | null
): OverviewMetric[] => {
  if (steps.length === 0) {
    return [];
  }
  const index = Math.min(Math.max(stepIndex, 0), steps.length - 1);
  const series = <T,>(read: (step: TimelineStep) => T): T[] => steps.map(read);

  return [
    buildMetric('npv', 'money', series((step) => step.field.npv_cumulative), index, null),
    buildMetric(
      'compensation',
      'percent',
      series((step) => step.field.compensation),
      index,
      compensationBand
    ),
    buildMetric('production', 'volume', series((step) => step.field.production), index, null),
    buildMetric('injection', 'volume', series((step) => step.field.injection), index, null),
    buildMetric('watercut', 'percent', series(averageWatercut), index, null),
    buildMetric('factToTarget', 'percent', series(averageFactToTarget), index, null),
    buildMetric('activeWells', 'count', series((step) => step.field.active_wells), index, null),
    buildMetric('shutWells', 'count', series(shutWellCount), index, null)
  ];
};
