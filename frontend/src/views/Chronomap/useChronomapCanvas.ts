import { useEffect, useRef, type RefObject } from 'react';
import type { TimelineStep } from '../../api/types';
import { devicePixelRatioOf } from '../shared/canvasColors';
import type { RowIndex } from '../shared/wellFacts';
import { cellColorCache, type CellContext } from './cells';
import {
  COLUMN_GAP,
  ROW_GAP,
  GUTTER_LEFT,
  GUTTER_TOP,
  columnX,
  labelStride,
  rowY,
  stepYearTicks,
  type ChronoGeometry
} from './geometry';
import type { ChronoRow } from './sortRows';

const TERMINAL_ALPHA = 0.4;
const AXIS_FONT = "9px 'JetBrains Mono', ui-monospace, monospace";

export const CURSOR_INK_WIDTH = 2;
export const CURSOR_RADIUS = 6;
export const CURSOR_HALO_WIDTH = 1;

export interface CursorColors {
  ink: string;
  halo: string;
}

export interface ChronoPaint {
  geometry: ChronoGeometry;
  rows: readonly ChronoRow[];
  steps: readonly TimelineStep[];
  index: RowIndex;
  context: CellContext;
  axisColor: string;
  surfaceColor: string;
}

export const paintChronomap = (
  ctx: CanvasRenderingContext2D,
  paint: ChronoPaint
): void => {
  const { geometry, rows, steps, index, context, axisColor, surfaceColor } = paint;
  const scale = typeof ctx.getTransform === 'function' ? ctx.getTransform().a || 1 : 1;
  const snap = (value: number): number => Math.round(value * scale) / scale;
  const device = 1 / scale;
  const columnGap = COLUMN_GAP > 0 ? device : 0;
  const rowGap = ROW_GAP > 0 ? device : 0;
  ctx.clearRect(0, 0, geometry.width, geometry.height);
  ctx.fillStyle = surfaceColor;
  ctx.fillRect(GUTTER_LEFT, GUTTER_TOP, geometry.plotWidth, geometry.plotHeight);

  const rowEdges: number[] = [];
  const rowHeights: number[] = [];
  for (let row = 0; row <= rows.length; row += 1) {
    rowEdges.push(snap(rowY(row, geometry.cellHeight)));
  }
  for (let row = 0; row < rows.length; row += 1) {
    rowHeights.push(Math.max(device, rowEdges[row + 1] - rowEdges[row] - rowGap));
  }

  const colorOf = cellColorCache(context);
  let painted = '';
  for (let column = 0; column < geometry.columns; column += 1) {
    const step = steps[column];
    const stepRows = index[column];
    const left = snap(columnX(column, geometry.cellWidth));
    const right = snap(columnX(column + 1, geometry.cellWidth));
    const width = Math.max(device, right - left - columnGap);
    ctx.globalAlpha = step !== undefined && step.terminal ? TERMINAL_ALPHA : 1;
    for (let row = 0; row < rows.length; row += 1) {
      const color = colorOf(stepRows?.get(rows[row].well));
      if (color !== painted) {
        ctx.fillStyle = color;
        painted = color;
      }
      ctx.fillRect(left, rowEdges[row], width, rowHeights[row]);
    }
  }
  ctx.globalAlpha = 1;

  ctx.fillStyle = axisColor;
  ctx.font = AXIS_FONT;
  ctx.textBaseline = 'top';
  ctx.textAlign = 'left';
  for (const tick of stepYearTicks(steps)) {
    ctx.fillRect(columnX(tick.column, geometry.cellWidth), GUTTER_TOP - 3, 1, 3);
    ctx.fillText(tick.year, columnX(tick.column, geometry.cellWidth) + 2, 1);
  }

  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  const stride = labelStride(geometry.cellHeight);
  for (let row = 0; row < rows.length; row += stride) {
    ctx.fillText(
      rows[row].well,
      GUTTER_LEFT - 4,
      rowY(row, geometry.cellHeight) + geometry.cellHeight / 2
    );
  }
  ctx.textBaseline = 'top';
};

const applyScale = (
  canvas: HTMLCanvasElement,
  geometry: ChronoGeometry,
  ratio: number
): CanvasRenderingContext2D | null => {
  canvas.width = Math.round(geometry.width * ratio);
  canvas.height = Math.round(geometry.height * ratio);
  canvas.style.width = `${geometry.width}px`;
  canvas.style.height = `${geometry.height}px`;
  const ctx = canvas.getContext('2d');
  if (ctx === null) {
    return null;
  }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return ctx;
};

export const useChronomapCanvas = (
  paint: ChronoPaint
): RefObject<HTMLCanvasElement | null> => {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (canvas === null || paint.geometry.columns === 0 || paint.geometry.rows === 0) {
      return;
    }
    const ctx = applyScale(canvas, paint.geometry, devicePixelRatioOf());
    if (ctx === null) {
      return;
    }
    paintChronomap(ctx, paint);
  }, [paint]);

  return ref;
};

export const paintCursor = (
  ctx: CanvasRenderingContext2D,
  geometry: ChronoGeometry,
  column: number,
  cursor: CursorColors
): void => {
  ctx.clearRect(0, 0, geometry.width, geometry.height);
  if (column < 0 || column >= geometry.columns) {
    return;
  }
  const left = columnX(column, geometry.cellWidth);
  const width = geometry.cellWidth;
  const outer = CURSOR_HALO_WIDTH + CURSOR_INK_WIDTH;
  const frame = (
    x: number,
    y: number,
    w: number,
    h: number,
    stroke: string,
    lineWidth: number
  ): void => {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = lineWidth;
    if (typeof ctx.roundRect === 'function') {
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, Math.min(CURSOR_RADIUS, w / 2));
      ctx.stroke();
      return;
    }
    ctx.strokeRect(x, y, w, h);
  };

  frame(
    left - outer + CURSOR_HALO_WIDTH / 2,
    GUTTER_TOP - outer + CURSOR_HALO_WIDTH / 2,
    width + 2 * outer - CURSOR_HALO_WIDTH,
    geometry.plotHeight + 2 * outer - CURSOR_HALO_WIDTH,
    cursor.halo,
    CURSOR_HALO_WIDTH
  );
  frame(
    left - CURSOR_INK_WIDTH / 2,
    GUTTER_TOP - CURSOR_INK_WIDTH / 2,
    width + CURSOR_INK_WIDTH,
    geometry.plotHeight + CURSOR_INK_WIDTH,
    cursor.ink,
    CURSOR_INK_WIDTH
  );
};

export const useCursorCanvas = (
  geometry: ChronoGeometry,
  column: number,
  cursor: CursorColors
): RefObject<HTMLCanvasElement | null> => {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const { ink, halo } = cursor;

  useEffect(() => {
    const canvas = ref.current;
    if (canvas === null || geometry.columns === 0 || geometry.rows === 0) {
      return;
    }
    const ctx = applyScale(canvas, geometry, devicePixelRatioOf());
    if (ctx === null) {
      return;
    }
    paintCursor(ctx, geometry, column, { ink, halo });
  }, [geometry, column, ink, halo]);

  return ref;
};
