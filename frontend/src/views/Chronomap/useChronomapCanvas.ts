import { useEffect, useRef, type RefObject } from 'react';
import type { TimelineStep } from '../../api/types';
import { devicePixelRatioOf, toCanvasColor } from '../shared/canvasColors';
import type { RowIndex } from '../shared/wellFacts';
import { cellRgb, type CellContext } from './cells';
import {
  CELL_HEIGHT,
  ROW_GAP,
  GUTTER_LEFT,
  GUTTER_TOP,
  columnX,
  labelStride,
  rowY,
  yearTicks,
  type ChronoGeometry
} from './geometry';
import type { ChronoRow } from './sortRows';

const TERMINAL_ALPHA = 0.4;
const AXIS_FONT = "9px 'JetBrains Mono', ui-monospace, monospace";

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
  ctx.fillStyle = surfaceColor;
  ctx.fillRect(0, 0, geometry.width, geometry.height);

  for (let column = 0; column < geometry.columns; column += 1) {
    const step = steps[column];
    const stepRows = index[column];
    const x = columnX(column, geometry.cellWidth);
    ctx.globalAlpha = step !== undefined && step.terminal ? TERMINAL_ALPHA : 1;
    for (let row = 0; row < rows.length; row += 1) {
      const entry = rows[row];
      ctx.fillStyle = toCanvasColor(cellRgb(stepRows?.get(entry.well), context));
      ctx.fillRect(x, rowY(row), geometry.cellWidth, CELL_HEIGHT - ROW_GAP);
    }
  }
  ctx.globalAlpha = 1;

  ctx.fillStyle = axisColor;
  ctx.font = AXIS_FONT;
  ctx.textBaseline = 'top';
  ctx.textAlign = 'left';
  for (const tick of yearTicks(steps.map((step) => step.date))) {
    ctx.fillRect(columnX(tick.column, geometry.cellWidth), GUTTER_TOP - 3, 1, 3);
    ctx.fillText(tick.year, columnX(tick.column, geometry.cellWidth) + 2, 1);
  }

  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  const stride = labelStride();
  for (let row = 0; row < rows.length; row += stride) {
    ctx.fillText(rows[row].well, GUTTER_LEFT - 4, rowY(row) + CELL_HEIGHT / 2);
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
  color: string
): void => {
  ctx.clearRect(0, 0, geometry.width, geometry.height);
  if (column < 0 || column >= geometry.columns) {
    return;
  }
  ctx.fillStyle = color;
  ctx.fillRect(columnX(column, geometry.cellWidth), GUTTER_TOP, geometry.cellWidth, geometry.plotHeight);
};

export const useCursorCanvas = (
  geometry: ChronoGeometry,
  column: number,
  color: string
): RefObject<HTMLCanvasElement | null> => {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (canvas === null || geometry.columns === 0 || geometry.rows === 0) {
      return;
    }
    const ctx = applyScale(canvas, geometry, devicePixelRatioOf());
    if (ctx === null) {
      return;
    }
    paintCursor(ctx, geometry, column, color);
  }, [geometry, column, color]);

  return ref;
};
