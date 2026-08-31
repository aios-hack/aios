import type { TimelineFile, TimelineWellRow } from '../../api/types';
import { actualRate } from '../../data/wellRow';
import { areaRadius, ratioColor, watercutColor } from '../../theme/scales';

export type MapMetric = 'watercut' | 'npv' | 'ratio';

export const MIN_RADIUS = 1.2;
export const MAX_RADIUS = 4.5;

export interface WellState {
  row: TimelineWellRow;
  radius: number;
  fill: string | null;
  stroke: string;
  hollow: boolean;
  commissioned: boolean;
}

export const rateCeiling = (timeline: TimelineFile | null): number => {
  if (timeline === null) {
    return 0;
  }
  let ceiling = 0;
  for (const step of timeline.steps) {
    for (const row of step.wells) {
      const rate = actualRate(row);
      if (rate > ceiling) {
        ceiling = rate;
      }
    }
  }
  return ceiling;
};

export const rowsAtStep = (
  timeline: TimelineFile | null,
  stepIndex: number
): Map<string, TimelineWellRow> => {
  const rows = new Map<string, TimelineWellRow>();
  if (timeline === null || timeline.steps.length === 0) {
    return rows;
  }
  const bounded = Math.min(Math.max(stepIndex, 0), timeline.steps.length - 1);
  const step = timeline.steps[bounded];
  if (step === undefined) {
    return rows;
  }
  for (const row of step.wells) {
    rows.set(row.well, row);
  }
  return rows;
};

export const npvFill = (value: number | undefined, ceiling: number): string => {
  if (value === undefined) {
    return 'var(--color-unknown)';
  }
  if (ceiling <= 0) {
    return 'var(--color-unknown)';
  }
  if (value < 0) {
    return 'var(--scale-ratio-low)';
  }
  return ratioColor(value / ceiling);
};

const metricFill = (
  metric: MapMetric,
  row: TimelineWellRow,
  npv: Map<string, number>,
  ceiling: number
): string => {
  if (metric === 'npv') {
    return npvFill(npv.get(row.well), ceiling);
  }
  if (metric === 'ratio') {
    return ratioColor(row.fact_to_target);
  }
  if (row.role === 'INJ') {
    return 'var(--color-injection)';
  }
  return watercutColor(row.watercut);
};

interface StateInput {
  metric: MapMetric;
  rateMax: number;
  npv: Map<string, number>;
  npvMax: number;
}

export const wellStateOf = (
  row: TimelineWellRow,
  { metric, rateMax, npv, npvMax }: StateInput
): WellState => {
  if (row.availability === 'NOT_COMMISSIONED') {
    return {
      row,
      radius: MIN_RADIUS,
      fill: null,
      stroke: 'var(--color-well-dim)',
      hollow: true,
      commissioned: false
    };
  }
  const radius = areaRadius(actualRate(row), rateMax, MIN_RADIUS, MAX_RADIUS);
  if (row.operating_status === 'SHUT') {
    return {
      row,
      radius,
      fill: null,
      stroke: 'var(--color-text-muted)',
      hollow: true,
      commissioned: true
    };
  }
  return {
    row,
    radius,
    fill: metricFill(metric, row, npv, npvMax),
    stroke: 'var(--color-surface-solid)',
    hollow: false,
    commissioned: true
  };
};
