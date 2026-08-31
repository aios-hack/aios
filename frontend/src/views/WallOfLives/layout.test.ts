import { describe, expect, it } from 'vitest';
import {
  LABEL_HEIGHT,
  MIN_COLUMNS,
  TILE_GAP,
  TILE_HEIGHT,
  TILE_HEIGHT_MAX,
  TILE_WIDTH,
  TILE_WIDTH_MAX,
  columnsFor,
  layoutOf,
  stepAt,
  stepX,
  tileHeightFor,
  tileIndexAt,
  tileWidthFor,
  tileX,
  tileY
} from './layout';

describe('columnsFor', () => {
  it('fits as many base tiles as the container holds', () => {
    expect(columnsFor(TILE_WIDTH)).toBe(1);
    expect(columnsFor(TILE_WIDTH * 2 + TILE_GAP)).toBe(2);
    expect(columnsFor(1000)).toBe(7);
  });

  it('always keeps at least one column, however narrow the container', () => {
    expect(columnsFor(0)).toBe(MIN_COLUMNS);
    expect(columnsFor(10)).toBe(MIN_COLUMNS);
    expect(columnsFor(-500)).toBe(MIN_COLUMNS);
  });
});

describe('tileWidthFor', () => {
  it('stretches the tiles to fill the row', () => {
    expect(tileWidthFor(4, 1000)).toBeGreaterThan(TILE_WIDTH);
    expect(tileWidthFor(7, 1000) * 7 + 6 * TILE_GAP).toBeCloseTo(1000);
  });

  it('never grows past the tile width ceiling', () => {
    expect(tileWidthFor(1, 1000)).toBe(TILE_WIDTH_MAX);
    expect(tileWidthFor(2, 100000)).toBe(TILE_WIDTH_MAX);
    expect(tileWidthFor(4, 10000)).toBeLessThanOrEqual(TILE_WIDTH_MAX);
  });

  it('never shrinks below the base tile width', () => {
    expect(tileWidthFor(10, 1000)).toBe(TILE_WIDTH);
    expect(tileWidthFor(50, 100)).toBe(TILE_WIDTH);
  });

  it('falls back to the base width when the container reports nothing usable', () => {
    expect(tileWidthFor(4, 0)).toBe(TILE_WIDTH);
    expect(tileWidthFor(4, -300)).toBe(TILE_WIDTH);
    expect(tileWidthFor(4, Number.NaN)).toBe(TILE_WIDTH);
    expect(tileWidthFor(4, Number.POSITIVE_INFINITY)).toBe(TILE_WIDTH);
    expect(tileWidthFor(0, 1000)).toBe(TILE_WIDTH);
    expect(tileWidthFor(-2, 1000)).toBe(TILE_WIDTH);
  });
});

describe('tileHeightFor', () => {
  it('stretches the tiles to fill the column', () => {
    expect(tileHeightFor(4, 1000)).toBeGreaterThan(TILE_HEIGHT);
  });

  it('never grows past the tile height ceiling', () => {
    expect(tileHeightFor(1, 1000)).toBe(TILE_HEIGHT_MAX);
    expect(tileHeightFor(4, 100000)).toBe(TILE_HEIGHT_MAX);
  });

  it('never shrinks below the base tile height', () => {
    expect(tileHeightFor(20, 1000)).toBe(TILE_HEIGHT);
    expect(tileHeightFor(30, 100)).toBe(TILE_HEIGHT);
  });

  it('falls back to the base height when the container reports nothing usable', () => {
    expect(tileHeightFor(4, 0)).toBe(TILE_HEIGHT);
    expect(tileHeightFor(4, -800)).toBe(TILE_HEIGHT);
    expect(tileHeightFor(4, Number.NaN)).toBe(TILE_HEIGHT);
    expect(tileHeightFor(0, 1000)).toBe(TILE_HEIGHT);
    expect(tileHeightFor(-5, 1000)).toBe(TILE_HEIGHT);
  });

  it('rounds the stretched height down to a whole pixel', () => {
    expect(Number.isInteger(tileHeightFor(7, 1000))).toBe(true);
  });
});

describe('layoutOf', () => {
  it('never asks for more columns than there are tiles', () => {
    const layout = layoutOf(3, 1000);
    expect(layout.columns).toBe(3);
    expect(layout.rows).toBe(1);
  });

  it('wraps into rows once the tiles outrun the container', () => {
    const layout = layoutOf(20, 1000);
    expect(layout.columns).toBe(7);
    expect(layout.rows).toBe(3);
  });

  it('reports an empty wall as having no rows and no height', () => {
    const layout = layoutOf(0, 1000);
    expect(layout.rows).toBe(0);
    expect(layout.height).toBe(0);
  });

  it('keeps the cells consistent with the tiles and the gaps', () => {
    const layout = layoutOf(5, 1000, 500);
    expect(layout.cellWidth).toBe(layout.tileWidth + TILE_GAP);
    expect(layout.cellHeight).toBe(layout.tileHeight + LABEL_HEIGHT + TILE_GAP);
    expect(layout.width).toBe(Math.round(layout.columns * layout.cellWidth - TILE_GAP));
  });

  it('stays within both ceilings whatever the container size', () => {
    for (const width of [0, 200, 1000, 4000]) {
      for (const height of [0, 200, 1000, 4000]) {
        const layout = layoutOf(9, width, height);
        expect(layout.tileWidth).toBeGreaterThanOrEqual(TILE_WIDTH);
        expect(layout.tileWidth).toBeLessThanOrEqual(TILE_WIDTH_MAX);
        expect(layout.tileHeight).toBeGreaterThanOrEqual(TILE_HEIGHT);
        expect(layout.tileHeight).toBeLessThanOrEqual(TILE_HEIGHT_MAX);
      }
    }
  });

  it('survives a container that has not been measured yet', () => {
    const layout = layoutOf(9, Number.NaN, Number.NaN);

    expect(Number.isNaN(layout.columns)).toBe(false);
    expect(Number.isNaN(layout.rows)).toBe(false);
    expect(Number.isNaN(layout.width)).toBe(false);
    expect(Number.isNaN(layout.height)).toBe(false);
    expect(layout.columns).toBeGreaterThanOrEqual(1);
  });

  it('survives an infinite container width', () => {
    const layout = layoutOf(9, Number.POSITIVE_INFINITY, 400);

    expect(Number.isFinite(layout.columns)).toBe(true);
    expect(Number.isFinite(layout.width)).toBe(true);
  });
});

describe('tileX and tileY', () => {
  const layout = layoutOf(9, 1000);

  it('walks a row left to right, then drops to the next one', () => {
    expect(tileX(0, layout)).toBe(0);
    expect(tileX(1, layout)).toBe(layout.cellWidth);
    expect(tileY(0, layout)).toBe(LABEL_HEIGHT);
    expect(tileY(layout.columns, layout)).toBe(layout.cellHeight + LABEL_HEIGHT);
  });
});

describe('stepX and stepAt', () => {
  it('spreads the steps across the tile', () => {
    expect(stepX(0, 5, 100)).toBe(0);
    expect(stepX(4, 5, 100)).toBe(100);
    expect(stepX(2, 5, 100)).toBe(50);
  });

  it('pins a single step to the left edge', () => {
    expect(stepX(0, 1, 100)).toBe(0);
    expect(stepX(0, 0, 100)).toBe(0);
    expect(stepAt(80, 1, 100)).toBe(0);
  });

  it('maps a pointer offset back to the nearest step', () => {
    expect(stepAt(0, 5, 100)).toBe(0);
    expect(stepAt(50, 5, 100)).toBe(2);
    expect(stepAt(100, 5, 100)).toBe(4);
  });

  it('clamps offsets that land outside the tile', () => {
    expect(stepAt(-40, 5, 100)).toBe(0);
    expect(stepAt(400, 5, 100)).toBe(4);
  });

  it('round-trips every step through its own position', () => {
    for (let step = 0; step < 6; step += 1) {
      expect(stepAt(stepX(step, 6, 100), 6, 100)).toBe(step);
    }
  });
});

describe('tileIndexAt', () => {
  const layout = layoutOf(9, 1000);

  it('finds the tile under a pointer inside the wall', () => {
    expect(tileIndexAt(1, 1, layout)).toBe(0);
    expect(tileIndexAt(layout.cellWidth + 1, 1, layout)).toBe(1);
    expect(tileIndexAt(1, layout.cellHeight + 1, layout)).toBe(layout.columns);
  });

  it('reports nothing outside the wall', () => {
    expect(tileIndexAt(-1, 1, layout)).toBeNull();
    expect(tileIndexAt(1, -1, layout)).toBeNull();
    expect(tileIndexAt(layout.columns * layout.cellWidth + 1, 1, layout)).toBeNull();
    expect(tileIndexAt(1, layout.rows * layout.cellHeight + 1, layout)).toBeNull();
  });

  it('reports nothing for the empty cells of a ragged last row', () => {
    const ragged = layoutOf(8, 1000);
    expect(ragged.rows).toBe(2);
    expect(tileIndexAt(6 * ragged.cellWidth + 1, ragged.cellHeight + 1, ragged)).toBeNull();
  });
});
