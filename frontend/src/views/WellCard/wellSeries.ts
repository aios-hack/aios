import type { TimelineFile, TimelineWellRow } from '../../api/types';

export type WellSeriesKey = 'rate' | 'watercut' | 'bhp';

export interface WellSeries {
  key: WellSeriesKey;
  values: (number | null)[];
  injector: boolean;
}

const rateOf = (row: TimelineWellRow): number | null => {
  if (row.role === 'INJ') {
    return row.injection_rate;
  }
  if (row.role === 'PROD') {
    return row.liquid_rate;
  }
  return null;
};

const valueOf = (row: TimelineWellRow, key: WellSeriesKey): number | null => {
  if (key === 'rate') {
    return rateOf(row);
  }
  if (key === 'watercut') {
    return row.watercut;
  }
  return row.bhp;
};

export const buildWellSeries = (
  timeline: TimelineFile,
  well: string
): WellSeries[] => {
  const column = timeline.wells.indexOf(well);
  if (column < 0) {
    return [];
  }
  const rate: (number | null)[] = [];
  const watercut: (number | null)[] = [];
  const bhp: (number | null)[] = [];
  let injectorSteps = 0;
  let roleSteps = 0;

  for (const step of timeline.steps) {
    const row = step.wells[column];
    if (row === undefined) {
      rate.push(null);
      watercut.push(null);
      bhp.push(null);
      continue;
    }
    if (row.role !== 'NONE') {
      roleSteps += 1;
      if (row.role === 'INJ') {
        injectorSteps += 1;
      }
    }
    rate.push(valueOf(row, 'rate'));
    watercut.push(valueOf(row, 'watercut'));
    bhp.push(valueOf(row, 'bhp'));
  }

  const injector = roleSteps > 0 && injectorSteps * 2 > roleSteps;
  return [
    { key: 'rate', values: rate, injector },
    { key: 'watercut', values: watercut, injector },
    { key: 'bhp', values: bhp, injector }
  ];
};
