import { useEffect, useState } from 'react';
import type { TimelineWellRow } from '../../api/types';
import { clamp01 } from '../../theme/scales';
import {
  mixColors,
  readPalette,
  samePalette,
  toCanvasColor,
  type Rgb
} from '../shared/canvasColors';
import { HISTORY_METRICS, type HistoryMetric } from '../shared/historyControls';

export type ChronoMetric = HistoryMetric;

export const CHRONO_METRICS: readonly ChronoMetric[] = HISTORY_METRICS;

export const PALETTE_TOKENS = [
  '--scale-watercut-0',
  '--scale-watercut-1',
  '--scale-ratio-low',
  '--scale-ratio-mid',
  '--scale-ratio-high',
  '--color-oil',
  '--color-injection',
  '--color-surface-sunken',
  '--color-plot-bg',
  '--color-plot-grid',
  '--color-well-dim',
  '--color-axis-tick',
  '--color-unknown',
  '--color-cursor-ink',
  '--color-cursor-halo'
] as const;

export type PaletteToken = (typeof PALETTE_TOKENS)[number];
export type Palette = Record<PaletteToken, Rgb>;

const FALLBACK: Rgb = { r: 128, g: 128, b: 128, a: 1 };

export const readChronoPalette = (root: Element | null): Palette =>
  readPalette(PALETTE_TOKENS, FALLBACK, root);

const documentRoot = (): Element | null =>
  typeof document === 'undefined' ? null : document.documentElement;

export const useChronoPalette = (theme: string): Palette => {
  const [palette, setPalette] = useState<Palette>(() =>
    readChronoPalette(documentRoot())
  );

  useEffect(() => {
    const sync = () => {
      const next = readChronoPalette(documentRoot());
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

export type CellMode = 'production' | 'injection' | 'shut' | 'idle';

export const modeOf = (row: TimelineWellRow): CellMode => {
  if (row.availability === 'NOT_COMMISSIONED') {
    return 'idle';
  }
  if (row.operating_status === 'SHUT') {
    return 'shut';
  }
  return row.role === 'INJ' ? 'injection' : 'production';
};

const idleColor = (palette: Palette): Rgb => {
  const dim = palette['--color-well-dim'];
  return { ...mixColors(palette['--color-plot-bg'], dim, dim.a), a: 1 };
};

const modeColor = (mode: CellMode, palette: Palette): Rgb => {
  if (mode === 'injection') {
    return palette['--color-injection'];
  }
  if (mode === 'production') {
    return palette['--color-oil'];
  }
  if (mode === 'shut') {
    return palette['--color-surface-sunken'];
  }
  return idleColor(palette);
};

const watercutRgb = (watercut: number | null, palette: Palette): Rgb => {
  if (watercut === null || Number.isNaN(watercut)) {
    return palette['--color-unknown'];
  }
  return mixColors(
    palette['--scale-watercut-0'],
    palette['--scale-watercut-1'],
    clamp01(watercut)
  );
};

const ratioRgb = (ratio: number | null, palette: Palette): Rgb => {
  if (ratio === null || Number.isNaN(ratio)) {
    return palette['--color-unknown'];
  }
  if (ratio >= 1) {
    return palette['--scale-ratio-high'];
  }
  return mixColors(
    palette['--scale-ratio-low'],
    palette['--scale-ratio-mid'],
    clamp01(ratio)
  );
};

const npvRgb = (value: number | undefined, ceiling: number, palette: Palette): Rgb => {
  if (value === undefined) {
    return palette['--color-unknown'];
  }
  if (ceiling <= 0) {
    return palette['--color-unknown'];
  }
  if (value < 0) {
    return palette['--scale-ratio-low'];
  }
  return ratioRgb(value / ceiling, palette);
};

export interface CellContext {
  metric: ChronoMetric;
  palette: Palette;
  npv: Map<string, number>;
  npvCeiling: number;
}

export const cellRgb = (
  row: TimelineWellRow | undefined,
  { metric, palette, npv, npvCeiling }: CellContext
): Rgb => {
  if (row === undefined) {
    return palette['--color-unknown'];
  }
  if (metric === 'mode') {
    return modeColor(modeOf(row), palette);
  }
  if (metric === 'npv') {
    return npvRgb(npv.get(row.well), npvCeiling, palette);
  }
  const mode = modeOf(row);
  if (mode === 'idle') {
    return idleColor(palette);
  }
  if (mode === 'shut') {
    return palette['--color-surface-sunken'];
  }
  if (metric === 'ratio') {
    return ratioRgb(row.fact_to_target, palette);
  }
  if (mode === 'injection') {
    return palette['--color-injection'];
  }
  return watercutRgb(row.watercut, palette);
};

export const cellColor = (
  row: TimelineWellRow | undefined,
  context: CellContext
): string => toCanvasColor(cellRgb(row, context));

const ALPHA_STEPS = 1000;

const byteOf = (channel: number): number => Math.round(clamp01(channel / 255) * 255);

const rgbKey = ({ r, g, b, a }: Rgb): number => {
  const alpha = a >= 1 ? ALPHA_STEPS + 1 : Math.round(clamp01(a) * ALPHA_STEPS);
  return (
    ((byteOf(r) * 256 + byteOf(g)) * 256 + byteOf(b)) * (ALPHA_STEPS + 2) + alpha
  );
};

export const cellColorCache = (
  context: CellContext
): ((row: TimelineWellRow | undefined) => string) => {
  const cache = new Map<number, string>();
  return (row) => {
    const rgb = cellRgb(row, context);
    const key = rgbKey(rgb);
    const hit = cache.get(key);
    if (hit !== undefined) {
      return hit;
    }
    const color = toCanvasColor(rgb);
    cache.set(key, color);
    return color;
  };
};
