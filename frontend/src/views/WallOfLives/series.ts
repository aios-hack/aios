import { useEffect, useState } from 'react';
import type { TimelineFile, TimelineWellRow } from '../../api/types';
import { readPalette, samePalette, type Rgb } from '../shared/canvasColors';
import { lastObservedIndex } from '../shared/wellFacts';

export { lastObservedIndex };

export const WALL_PALETTE_TOKENS = [
  '--scale-watercut-0',
  '--scale-watercut-1',
  '--color-oil',
  '--color-injection',
  '--color-plot-bg',
  '--color-axis-tick',
  '--color-border-strong',
  '--color-accent',
  '--color-unknown'
] as const;

export type WallToken = (typeof WALL_PALETTE_TOKENS)[number];
export type WallPalette = Record<WallToken, Rgb>;

const FALLBACK: Rgb = { r: 128, g: 128, b: 128, a: 1 };

export const readWallPalette = (root: Element | null): WallPalette =>
  readPalette(WALL_PALETTE_TOKENS, FALLBACK, root);

const documentRoot = (): Element | null =>
  typeof document === 'undefined' ? null : document.documentElement;

export const useWallPalette = (theme: string): WallPalette => {
  const [palette, setPalette] = useState<WallPalette>(() =>
    readWallPalette(documentRoot())
  );

  useEffect(() => {
    const sync = () => {
      const next = readWallPalette(documentRoot());
      setPalette((current) => (samePalette(current, next) ? current : next));
    };
    sync();
    const root = documentRoot();
    if (root === null || typeof MutationObserver !== 'function') {
      return;
    }
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, [theme]);

  return palette;
};

export interface SeriesPoint {
  rate: number | null;
  watercut: number | null;
  shut: boolean;
  idle: boolean;
}

export interface WellSeries {
  well: string;
  injector: boolean;
  points: SeriesPoint[];
  lastWatercut: number | null;
}

const rateOf = (row: TimelineWellRow): number | null =>
  row.availability === 'NOT_COMMISSIONED'
    ? null
    : row.role === 'INJ'
      ? row.injection_rate
      : row.liquid_rate;

export const buildSeries = (timeline: TimelineFile): Map<string, WellSeries> => {
  const series = new Map<string, WellSeries>();
  for (const well of timeline.wells) {
    series.set(well, { well, injector: false, points: [], lastWatercut: null });
  }
  const observed = lastObservedIndex(timeline);
  timeline.steps.forEach((step, index) => {
    for (const row of step.wells) {
      const entry = series.get(row.well);
      if (entry === undefined) {
        continue;
      }
      if (row.role === 'INJ') {
        entry.injector = true;
      }
      entry.points.push({
        rate: rateOf(row),
        watercut: row.watercut,
        shut: row.operating_status === 'SHUT',
        idle: row.availability === 'NOT_COMMISSIONED'
      });
      if (index === observed) {
        entry.lastWatercut = row.watercut;
      }
    }
  });
  return series;
};

export const seriesCeiling = (series: Map<string, WellSeries>): number => {
  let ceiling = 0;
  for (const entry of series.values()) {
    for (const point of entry.points) {
      if (point.rate !== null && point.rate > ceiling) {
        ceiling = point.rate;
      }
    }
  }
  return ceiling;
};

export const watercutByWell = (series: Map<string, WellSeries>): Map<string, number> => {
  const values = new Map<string, number>();
  for (const entry of series.values()) {
    if (entry.lastWatercut !== null && !Number.isNaN(entry.lastWatercut)) {
      values.set(entry.well, entry.lastWatercut);
    }
  }
  return values;
};
