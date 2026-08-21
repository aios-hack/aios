import type { GraphFile, NpvFile, TimelineFile, TimelineWellRow } from '../../api/types';
import { compareWellIds } from '../../ui/format';
import type { HistorySort } from './historyControls';

export const UNGROUPED = null;

export interface WellRow {
  well: string;
  group: string | null;
  npv: number | undefined;
  watercut: number | undefined;
}

export const npvByWell = (npv: NpvFile | null): Map<string, number> => {
  const values = new Map<string, number>();
  if (npv === null) {
    return values;
  }
  for (const row of npv.wells) {
    values.set(row.well, row.with_allocated_tax);
  }
  return values;
};

export const npvCeilingOf = (values: Map<string, number>): number => {
  let ceiling = 0;
  for (const value of values.values()) {
    const magnitude = Math.abs(value);
    if (magnitude > ceiling) {
      ceiling = magnitude;
    }
  }
  return ceiling;
};

export const groupByWell = (graph: GraphFile | null): Map<string, string> => {
  const groups = new Map<string, string>();
  if (graph === null) {
    return groups;
  }
  for (const group of graph.groups) {
    for (const well of group.wells) {
      groups.set(well, group.id);
    }
  }
  return groups;
};

export const buildWellRows = (
  wells: readonly string[],
  groups: Map<string, string>,
  npv: Map<string, number>,
  watercut: Map<string, number> = new Map()
): WellRow[] =>
  wells.map((well) => ({
    well,
    group: groups.get(well) ?? UNGROUPED,
    npv: npv.get(well),
    watercut: watercut.get(well)
  }));

export const byWell = (a: WellRow, b: WellRow): number => compareWellIds(a.well, b.well);

export const byGroup = (a: WellRow, b: WellRow): number => {
  if (a.group === b.group) {
    return byWell(a, b);
  }
  if (a.group === UNGROUPED) {
    return 1;
  }
  if (b.group === UNGROUPED) {
    return -1;
  }
  return a.group.localeCompare(b.group) || byWell(a, b);
};

export const byNpv = (a: WellRow, b: WellRow): number => {
  if (a.npv === undefined || b.npv === undefined) {
    if (a.npv === b.npv) {
      return byWell(a, b);
    }
    return a.npv === undefined ? 1 : -1;
  }
  return b.npv - a.npv || byWell(a, b);
};

export const byWatercut = (a: WellRow, b: WellRow): number => {
  if (a.watercut === undefined || b.watercut === undefined) {
    if (a.watercut === b.watercut) {
      return byWell(a, b);
    }
    return a.watercut === undefined ? 1 : -1;
  }
  return b.watercut - a.watercut || byWell(a, b);
};

const HISTORY_COMPARATORS: Record<HistorySort, (a: WellRow, b: WellRow) => number> = {
  well: byWell,
  group: byGroup,
  npv: byNpv,
  watercut: byWatercut
};

export const sortWellRows = (rows: readonly WellRow[], sort: HistorySort): WellRow[] =>
  [...rows].sort(HISTORY_COMPARATORS[sort]);

export const ungroupedCount = (rows: readonly WellRow[]): number =>
  rows.reduce((count, row) => (row.group === UNGROUPED ? count + 1 : count), 0);

export const lastObservedIndex = (timeline: TimelineFile): number => {
  for (let i = timeline.steps.length - 1; i >= 0; i -= 1) {
    if (!timeline.steps[i].terminal) {
      return i;
    }
  }
  return -1;
};

export const lastWatercutByWell = (timeline: TimelineFile): Map<string, number> => {
  const values = new Map<string, number>();
  const observed = lastObservedIndex(timeline);
  if (observed < 0) {
    return values;
  }
  for (const row of timeline.steps[observed].wells) {
    if (row.watercut !== null && !Number.isNaN(row.watercut)) {
      values.set(row.well, row.watercut);
    }
  }
  return values;
};

export type RowIndex = Map<string, TimelineWellRow>[];

export const indexSteps = (timeline: TimelineFile | null): RowIndex => {
  if (timeline === null) {
    return [];
  }
  return timeline.steps.map((step) => {
    const rows = new Map<string, TimelineWellRow>();
    for (const row of step.wells) {
      rows.set(row.well, row);
    }
    return rows;
  });
};
