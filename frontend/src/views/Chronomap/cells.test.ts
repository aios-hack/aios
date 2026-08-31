import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { TimelineFile, TimelineWellRow } from '../../api/types';
import {
  cellColor,
  cellColorCache,
  cellRgb,
  CHRONO_METRICS,
  type CellContext,
  type Palette
} from './cells';
import { PALETTE_TOKENS } from './cells';

const timeline = JSON.parse(
  readFileSync(resolve(__dirname, '../../../public/data/timeline.json'), 'utf8')
) as TimelineFile;

const CHANNELS: readonly (readonly [number, number, number])[] = [
  [11, 29, 42],
  [79, 195, 247],
  [198, 40, 40],
  [249, 168, 37],
  [46, 125, 50],
  [123, 31, 162],
  [0, 131, 143],
  [22, 27, 34],
  [13, 17, 23],
  [48, 54, 61],
  [72, 79, 88],
  [139, 148, 158],
  [110, 118, 129],
  [230, 237, 243],
  [31, 111, 235]
];

const palette = (): Palette => {
  const result = {} as Palette;
  PALETTE_TOKENS.forEach((token, i) => {
    const [r, g, b] = CHANNELS[i];
    result[token] = { r, g, b, a: i === 10 ? 0.42 : 1 };
  });
  return result;
};

const allRows = (): (TimelineWellRow | undefined)[] => {
  const rows: (TimelineWellRow | undefined)[] = [undefined];
  for (const step of timeline.steps) {
    for (const row of step.wells) {
      rows.push(row);
    }
  }
  return rows;
};

const npvMap = (rows: readonly (TimelineWellRow | undefined)[]): Map<string, number> => {
  const map = new Map<string, number>();
  let n = 0;
  for (const row of rows) {
    if (row === undefined) {
      continue;
    }
    if (!map.has(row.well)) {
      map.set(row.well, (n % 7 === 0 ? -1 : 1) * (n * 1234.567) % 90000);
      n += 1;
    }
  }
  return map;
};

describe('cellColorCache matches the exact path on the real dataset', () => {
  const rows = allRows();
  const npv = npvMap(rows);

  it('covers the full timeline', () => {
    expect(timeline.steps.length).toBe(225);
    expect(rows.length).toBe(23176);
  });

  for (const metric of CHRONO_METRICS) {
    for (const npvCeiling of [0, 90000]) {
      it(`is byte-identical for metric=${metric} ceiling=${npvCeiling}`, () => {
        const context: CellContext = { metric, palette: palette(), npv, npvCeiling };
        const cached = cellColorCache(context);
        let checked = 0;
        for (const row of rows) {
          expect(cached(row)).toBe(cellColor(row, context));
          checked += 1;
        }
        expect(checked).toBe(rows.length);
      });
    }
  }

  it('stays byte-identical across randomised palettes', () => {
    let seed = 20260831;
    const next = (): number => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    for (let trial = 0; trial < 25; trial += 1) {
      const random = {} as Palette;
      for (const token of PALETTE_TOKENS) {
        random[token] = {
          r: next() * 255,
          g: next() * 255,
          b: next() * 255,
          a: next() < 0.3 ? next() : 1
        };
      }
      const metric = CHRONO_METRICS[trial % CHRONO_METRICS.length];
      const context: CellContext = { metric, palette: random, npv, npvCeiling: 90000 };
      const cached = cellColorCache(context);
      for (const row of rows) {
        expect(cached(row)).toBe(cellColor(row, context));
      }
    }
  });

  it('keeps translucent palette entries distinct', () => {
    const base = palette();
    const translucent = { ...base } as Palette;
    translucent['--color-unknown'] = { r: 10, g: 20, b: 30, a: 0.1 };
    const other = { ...translucent } as Palette;
    other['--color-unknown'] = { r: 10, g: 20, b: 30, a: 0.356 };
    const ctxA: CellContext = { metric: 'watercut', palette: translucent, npv, npvCeiling: 0 };
    const ctxB: CellContext = { metric: 'watercut', palette: other, npv, npvCeiling: 0 };
    expect(cellColorCache(ctxA)(undefined)).toBe('rgba(10, 20, 30, 0.100)');
    expect(cellColorCache(ctxB)(undefined)).toBe('rgba(10, 20, 30, 0.356)');
  });
});

describe('npv cells with an unmeasurable ceiling', () => {
  const rowFor = (well: string): TimelineWellRow => ({
    well,
    availability: 'AVAILABLE',
    role: 'PROD',
    operating_status: 'OPEN',
    setpoint: 1,
    liquid_rate: 1,
    injection_rate: 0,
    bhp: 1,
    watercut: null,
    fact_to_target: null,
    cumulative_liquid: 1
  });

  it('paints the unknown colour rather than a mid-scale reading', () => {
    const pal = palette();
    const context: CellContext = {
      metric: 'npv',
      palette: pal,
      npv: new Map([['W1', 0]]),
      npvCeiling: 0
    };
    expect(cellRgb(rowFor('W1'), context)).toEqual(pal['--color-unknown']);
    expect(cellRgb(rowFor('W1'), context)).not.toEqual(pal['--scale-ratio-mid']);
  });

  it('paints a well absent from npv.json as unknown', () => {
    const pal = palette();
    const context: CellContext = {
      metric: 'npv',
      palette: pal,
      npv: new Map([['W1', 50]]),
      npvCeiling: 50
    };
    expect(cellRgb(rowFor('W2'), context)).toEqual(pal['--color-unknown']);
  });

  it('still resolves a real ratio once the ceiling is measurable', () => {
    const pal = palette();
    const context: CellContext = {
      metric: 'npv',
      palette: pal,
      npv: new Map([['W1', 50]]),
      npvCeiling: 50
    };
    expect(cellRgb(rowFor('W1'), context)).not.toEqual(pal['--color-unknown']);
  });
});
