import { useEffect, useRef, type RefObject } from 'react';
import { devicePixelRatioOf, mixColors, toCanvasColor } from '../shared/canvasColors';
import {
  stepX,
  tileX,
  tileY,
  type WallLayout
} from './layout';
import type { WallPalette, WellSeries } from './series';
import type { WallRow } from './wallSort';

const LABEL_FONT = "9px 'JetBrains Mono', ui-monospace, monospace";
const IDLE_ALPHA = 0.28;
const FILL_ALPHA = 0.82;
const SHUT_ALPHA = 0.7;

export interface WallPaint {
  layout: WallLayout;
  rows: readonly WallRow[];
  series: Map<string, WellSeries>;
  ceiling: number;
  palette: WallPalette;
}

const rateY = (rate: number, ceiling: number, tileHeight: number): number =>
  ceiling <= 0 ? tileHeight : tileHeight - (rate / ceiling) * tileHeight;

const paintTile = (
  ctx: CanvasRenderingContext2D,
  entry: WellSeries,
  row: WallRow,
  originX: number,
  originY: number,
  paint: WallPaint
): void => {
  const { palette, ceiling, layout } = paint;
  const tileWidth = layout.tileWidth;
  const tileHeight = layout.tileHeight;
  const count = entry.points.length;
  ctx.fillStyle = toCanvasColor(palette['--color-plot-bg']);
  ctx.fillRect(originX, originY, tileWidth, tileHeight);

  const columnWidth = count <= 1 ? tileWidth : tileWidth / (count - 1);
  ctx.globalAlpha = FILL_ALPHA;
  entry.points.forEach((point, index) => {
    if (point.rate === null || point.idle) {
      return;
    }
    const x = originX + stepX(index, count, tileWidth);
    const top = originY + rateY(point.rate, ceiling, tileHeight);
    const color =
      point.watercut === null || Number.isNaN(point.watercut)
        ? palette['--color-unknown']
        : mixColors(
            palette['--scale-watercut-0'],
            palette['--scale-watercut-1'],
            point.watercut
          );
    ctx.fillStyle = toCanvasColor(color);
    ctx.fillRect(x, top, columnWidth, originY + tileHeight - top);
  });
  ctx.globalAlpha = 1;

  ctx.strokeStyle = toCanvasColor(
    entry.injector ? palette['--color-injection'] : palette['--color-oil']
  );
  ctx.lineWidth = 1;
  ctx.beginPath();
  let started = false;
  entry.points.forEach((point, index) => {
    if (point.rate === null || point.idle) {
      started = false;
      return;
    }
    const x = originX + stepX(index, count, tileWidth);
    const y = originY + rateY(point.rate, ceiling, tileHeight);
    if (started) {
      ctx.lineTo(x, y);
    } else {
      ctx.moveTo(x, y);
      started = true;
    }
  });
  ctx.stroke();

  ctx.globalAlpha = SHUT_ALPHA;
  ctx.fillStyle = toCanvasColor(palette['--color-axis-tick']);
  entry.points.forEach((point, index) => {
    const previous = entry.points[index - 1];
    if (!point.shut || point.idle || (previous !== undefined && previous.shut)) {
      return;
    }
    ctx.fillRect(originX + stepX(index, count, tileWidth), originY, 1, tileHeight);
  });
  ctx.globalAlpha = IDLE_ALPHA;
  ctx.fillStyle = toCanvasColor(palette['--color-unknown']);
  entry.points.forEach((point, index) => {
    if (!point.idle) {
      return;
    }
    ctx.fillRect(originX + stepX(index, count, tileWidth), originY, columnWidth, tileHeight);
  });
  ctx.globalAlpha = 1;

  ctx.strokeStyle = toCanvasColor(palette['--color-border-strong']);
  ctx.strokeRect(originX + 0.5, originY + 0.5, tileWidth - 1, tileHeight - 1);

  ctx.fillStyle = toCanvasColor(palette['--color-axis-tick']);
  ctx.font = LABEL_FONT;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'bottom';
  ctx.fillText(row.well, originX, originY - 2, tileWidth);
};

export const paintWall = (ctx: CanvasRenderingContext2D, paint: WallPaint): void => {
  const { layout, rows, series } = paint;
  ctx.clearRect(0, 0, layout.width, layout.height);
  rows.forEach((row, index) => {
    const entry = series.get(row.well);
    if (entry === undefined) {
      return;
    }
    paintTile(ctx, entry, row, tileX(index, layout), tileY(index, layout), paint);
  });
};

const applyScale = (
  canvas: HTMLCanvasElement,
  layout: WallLayout,
  ratio: number
): CanvasRenderingContext2D | null => {
  canvas.width = Math.round(layout.width * ratio);
  canvas.height = Math.round(layout.height * ratio);
  canvas.style.width = `${layout.width}px`;
  canvas.style.height = `${layout.height}px`;
  const ctx = canvas.getContext('2d');
  if (ctx === null) {
    return null;
  }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return ctx;
};

export const useWallCanvas = (paint: WallPaint): RefObject<HTMLCanvasElement | null> => {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (canvas === null || paint.layout.rows === 0 || paint.layout.columns === 0) {
      return;
    }
    const ctx = applyScale(canvas, paint.layout, devicePixelRatioOf());
    if (ctx === null) {
      return;
    }
    paintWall(ctx, paint);
  }, [paint]);

  return ref;
};

export const paintWallCursor = (
  ctx: CanvasRenderingContext2D,
  layout: WallLayout,
  step: number,
  steps: number,
  color: string
): void => {
  ctx.clearRect(0, 0, layout.width, layout.height);
  if (step < 0 || step >= steps || layout.count === 0) {
    return;
  }
  ctx.fillStyle = color;
  const offset = stepX(step, steps, layout.tileWidth);
  for (let index = 0; index < layout.count; index += 1) {
    ctx.fillRect(tileX(index, layout) + offset, tileY(index, layout), 1, layout.tileHeight);
  }
};

export const useWallCursor = (
  layout: WallLayout,
  step: number,
  steps: number,
  color: string
): RefObject<HTMLCanvasElement | null> => {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (canvas === null || layout.rows === 0 || layout.columns === 0) {
      return;
    }
    const ctx = applyScale(canvas, layout, devicePixelRatioOf());
    if (ctx === null) {
      return;
    }
    paintWallCursor(ctx, layout, step, steps, color);
  }, [layout, step, steps, color]);

  return ref;
};
