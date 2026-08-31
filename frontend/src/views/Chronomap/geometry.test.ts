import { describe, expect, it } from 'vitest';
import {
  CELL_HEIGHT,
  CELL_HEIGHT_MAX,
  CELL_WIDTH,
  CELL_WIDTH_MAX,
  GUTTER_LEFT,
  GUTTER_RIGHT,
  GUTTER_TOP,
  cellHeightFor,
  cellWidthFor,
  columnX,
  geometryOf,
  hitTest,
  labelStride,
  rowY,
  yearTicks,
  stepYearTicks
} from './geometry';

const isDevicePixelAligned = (size: number, ratio: number): boolean =>
  Number.isInteger(Math.round(size * ratio * 1e6) / 1e6);

describe('cellWidthFor', () => {
  it('never goes below the base cell width', () => {
    expect(cellWidthFor(500, 1000)).toBe(CELL_WIDTH);
    expect(cellWidthFor(500, 1000, 2)).toBe(CELL_WIDTH);
    expect(cellWidthFor(1000, 200, 3)).toBe(CELL_WIDTH);
  });

  it('never grows past the cell width ceiling', () => {
    expect(cellWidthFor(1, 4000)).toBe(CELL_WIDTH_MAX);
    expect(cellWidthFor(10, 4000, 2)).toBe(CELL_WIDTH_MAX);
    expect(cellWidthFor(2, 100000, 3)).toBeLessThanOrEqual(CELL_WIDTH_MAX);
  });

  it('falls back to the base width when the container reports nothing usable', () => {
    expect(cellWidthFor(0, 1000, 2)).toBe(CELL_WIDTH);
    expect(cellWidthFor(-4, 1000, 2)).toBe(CELL_WIDTH);
    expect(cellWidthFor(10, Number.NaN, 2)).toBe(CELL_WIDTH);
    expect(cellWidthFor(10, Number.POSITIVE_INFINITY, 2)).toBe(CELL_WIDTH);
    expect(cellWidthFor(10, GUTTER_LEFT + GUTTER_RIGHT, 2)).toBe(CELL_WIDTH);
    expect(cellWidthFor(10, 0, 2)).toBe(CELL_WIDTH);
  });

  it('quantises the cell to whole device pixels so every column is the same width', () => {
    const raw = (1000 - GUTTER_LEFT - GUTTER_RIGHT) / 120;
    expect(Number.isInteger(raw)).toBe(false);
    const width = cellWidthFor(120, 1000, 2);
    expect(width).toBe(7.5);
    expect(isDevicePixelAligned(width, 2)).toBe(true);
    expect(width).toBeLessThanOrEqual(raw);
  });

  it('quantises to whole pixels at every device ratio it is given', () => {
    for (const ratio of [1, 2, 3]) {
      const width = cellWidthFor(120, 1000, ratio);
      expect(isDevicePixelAligned(width, ratio)).toBe(true);
    }
  });

  it('treats a nonsense ratio as a plain one-to-one screen', () => {
    expect(cellWidthFor(120, 1000, 0)).toBe(cellWidthFor(120, 1000, 1));
    expect(cellWidthFor(120, 1000, -2)).toBe(cellWidthFor(120, 1000, 1));
    expect(cellWidthFor(120, 1000, Number.NaN)).toBe(cellWidthFor(120, 1000, 1));
  });

  it('lays every column on the same grid, leaving no fractional drift', () => {
    const columns = 120;
    const width = cellWidthFor(columns, 1000, 2);
    const edges = Array.from({ length: columns }, (_, index) => columnX(index, width));
    for (const edge of edges) {
      expect(isDevicePixelAligned(edge, 2)).toBe(true);
    }
    const widths = edges.slice(1).map((edge, index) => edge - edges[index]);
    expect(new Set(widths.map((value) => Math.round(value * 1e6)))).toHaveLength(1);
  });
});

describe('rowY', () => {
  it('stacks the rows below the top gutter', () => {
    expect(rowY(0, 7)).toBe(GUTTER_TOP);
    expect(rowY(3, 7)).toBe(GUTTER_TOP + 21);
  });
});

describe('cellHeightFor', () => {
  it('never goes below the base cell height', () => {
    expect(cellHeightFor(200, 500)).toBe(CELL_HEIGHT);
    expect(cellHeightFor(200, 500, 2)).toBe(CELL_HEIGHT);
  });

  it('never grows past the cell height ceiling', () => {
    expect(cellHeightFor(1, 4000)).toBe(CELL_HEIGHT_MAX);
    expect(cellHeightFor(10, 500, 2)).toBe(CELL_HEIGHT_MAX);
  });

  it('falls back to the base height when the container reports nothing usable', () => {
    expect(cellHeightFor(0, 500, 2)).toBe(CELL_HEIGHT);
    expect(cellHeightFor(-3, 500, 2)).toBe(CELL_HEIGHT);
    expect(cellHeightFor(10, Number.NaN, 2)).toBe(CELL_HEIGHT);
    expect(cellHeightFor(10, GUTTER_TOP, 2)).toBe(CELL_HEIGHT);
  });

  it('quantises the row height to whole device pixels', () => {
    const raw = (500 - GUTTER_TOP) / 50;
    expect(Number.isInteger(raw)).toBe(false);
    const height = cellHeightFor(50, 500, 2);
    expect(height).toBe(9.5);
    expect(isDevicePixelAligned(height, 2)).toBe(true);
    expect(height).toBeLessThanOrEqual(raw);
  });

  it('treats a nonsense ratio as a plain one-to-one screen', () => {
    expect(cellHeightFor(50, 500, 0)).toBe(cellHeightFor(50, 500, 1));
    expect(cellHeightFor(50, 500, Number.NaN)).toBe(cellHeightFor(50, 500, 1));
  });
});

describe('geometryOf', () => {
  it('adds the gutters around the plotted cells', () => {
    const geometry = geometryOf(10, 4, 5, 7);
    expect(geometry.plotWidth).toBe(50);
    expect(geometry.plotHeight).toBe(28);
    expect(geometry.width).toBe(GUTTER_LEFT + 50 + GUTTER_RIGHT);
    expect(geometry.height).toBe(GUTTER_TOP + 28);
  });

  it('rounds a fractional plot to whole pixels', () => {
    const geometry = geometryOf(3, 3, 7.5, 9.5);
    expect(geometry.plotWidth).toBe(23);
    expect(geometry.plotHeight).toBe(29);
  });

  it('collapses to the gutters when there is nothing to draw', () => {
    const geometry = geometryOf(0, 0);
    expect(geometry.plotWidth).toBe(0);
    expect(geometry.height).toBe(GUTTER_TOP);
  });
});

describe('hitTest', () => {
  const geometry = geometryOf(4, 3, 5, 7);

  it('maps a point inside the plot to its cell', () => {
    expect(hitTest(GUTTER_LEFT + 1, GUTTER_TOP + 1, geometry)).toEqual({
      column: 0,
      row: 0
    });
    expect(hitTest(GUTTER_LEFT + 12, GUTTER_TOP + 15, geometry)).toEqual({
      column: 2,
      row: 2
    });
  });

  it('reports nothing for points in the gutters or past the plot', () => {
    expect(hitTest(0, 0, geometry)).toBeNull();
    expect(hitTest(GUTTER_LEFT - 1, GUTTER_TOP + 1, geometry)).toBeNull();
    expect(hitTest(GUTTER_LEFT + 1, GUTTER_TOP - 1, geometry)).toBeNull();
    expect(hitTest(GUTTER_LEFT + 100, GUTTER_TOP + 1, geometry)).toBeNull();
    expect(hitTest(GUTTER_LEFT + 1, GUTTER_TOP + 100, geometry)).toBeNull();
  });
});

describe('labelStride', () => {
  it('labels every row once the rows are tall enough to read', () => {
    expect(labelStride(CELL_HEIGHT_MAX)).toBe(1);
    expect(labelStride(20)).toBe(1);
  });

  it('thins the labels on cramped rows', () => {
    expect(labelStride(1)).toBe(11);
    expect(labelStride(CELL_HEIGHT)).toBe(2);
  });
});

describe('yearTicks', () => {
  it('emits one tick at the first column of each calendar year', () => {
    const ticks = yearTicks(['2007-01-01', '2007-06-01', '2008-01-01', '2009-03-01']);
    expect(ticks).toEqual([
      { column: 0, year: '2007' },
      { column: 2, year: '2008' },
      { column: 3, year: '2009' }
    ]);
  });

  it('emits nothing for an empty timeline', () => {
    expect(yearTicks([])).toEqual([]);
  });

  it('re-emits a year that comes back after another one', () => {
    expect(yearTicks(['2007-01-01', '2008-01-01', '2007-01-01'])).toHaveLength(3);
  });
});

describe('stepYearTicks', () => {
  it('marks the first column of every year exactly once', () => {
    const steps = [
      { date: '2007-01-01' },
      { date: '2007-07-01' },
      { date: '2008-01-01' },
      { date: '2009-01-01' },
      { date: '2009-06-01' }
    ];
    expect(stepYearTicks(steps)).toEqual([
      { column: 0, year: '2007' },
      { column: 2, year: '2008' },
      { column: 3, year: '2009' }
    ]);
  });

  it('agrees with the date based reading and handles an empty run', () => {
    const steps = [{ date: '2010-03-01' }, { date: '2011-03-01' }];
    expect(stepYearTicks(steps)).toEqual(yearTicks(steps.map((step) => step.date)));
    expect(stepYearTicks([])).toEqual([]);
  });
});
