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

const WATERCUT_STEPS = 1020;

interface WallInk {
  plotBg: string;
  unknown: string;
  axisTick: string;
  borderStrong: string;
  oil: string;
  injection: string;
  watercutAt: (watercut: number) => string;
}

const wallInk = (palette: WallPalette): WallInk => {
  const ramp: (string | undefined)[] = new Array(WATERCUT_STEPS + 1);
  const low = palette['--scale-watercut-0'];
  const high = palette['--scale-watercut-1'];
  return {
    plotBg: toCanvasColor(palette['--color-plot-bg']),
    unknown: toCanvasColor(palette['--color-unknown']),
    axisTick: toCanvasColor(palette['--color-axis-tick']),
    borderStrong: toCanvasColor(palette['--color-border-strong']),
    oil: toCanvasColor(palette['--color-oil']),
    injection: toCanvasColor(palette['--color-injection']),
    watercutAt: (watercut) => {
      const slot = Math.round(
        (watercut <= 0 ? 0 : watercut >= 1 ? 1 : watercut) * WATERCUT_STEPS
      );
      const hit = ramp[slot];
      if (hit !== undefined) {
        return hit;
      }
      const color = toCanvasColor(mixColors(low, high, watercut));
      ramp[slot] = color;
      return color;
    }
  };
};

const rateY = (rate: number, ceiling: number, tileHeight: number): number =>
  ceiling <= 0 ? tileHeight : tileHeight - (rate / ceiling) * tileHeight;

const paintTile = (
  ctx: CanvasRenderingContext2D,
  entry: WellSeries,
  row: WallRow,
  originX: number,
  originY: number,
  paint: WallPaint,
  ink: WallInk
): void => {
  const { ceiling, layout } = paint;
  const tileWidth = layout.tileWidth;
  const tileHeight = layout.tileHeight;
  const points = entry.points;
  const count = points.length;
  ctx.fillStyle = ink.plotBg;
  ctx.fillRect(originX, originY, tileWidth, tileHeight);

  const columnWidth = count <= 1 ? tileWidth : tileWidth / (count - 1);
  const baseline = originY + tileHeight;
  ctx.globalAlpha = FILL_ALPHA;
  let filled = '';
  for (let index = 0; index < count; index += 1) {
    const point = points[index];
    if (point.rate === null || point.idle) {
      continue;
    }
    const x = originX + stepX(index, count, tileWidth);
    const top = originY + rateY(point.rate, ceiling, tileHeight);
    const color =
      point.watercut === null || Number.isNaN(point.watercut)
        ? ink.unknown
        : ink.watercutAt(point.watercut);
    if (color !== filled) {
      ctx.fillStyle = color;
      filled = color;
    }
    ctx.fillRect(x, top, columnWidth, baseline - top);
  }
  ctx.globalAlpha = 1;

  ctx.strokeStyle = entry.injector ? ink.injection : ink.oil;
  ctx.lineWidth = 1;
  ctx.beginPath();
  let started = false;
  for (let index = 0; index < count; index += 1) {
    const point = points[index];
    if (point.rate === null || point.idle) {
      started = false;
      continue;
    }
    const x = originX + stepX(index, count, tileWidth);
    const y = originY + rateY(point.rate, ceiling, tileHeight);
    if (started) {
      ctx.lineTo(x, y);
    } else {
      ctx.moveTo(x, y);
      started = true;
    }
  }
  ctx.stroke();

  ctx.globalAlpha = SHUT_ALPHA;
  ctx.fillStyle = ink.axisTick;
  for (let index = 0; index < count; index += 1) {
    const point = points[index];
    const previous = points[index - 1];
    if (!point.shut || point.idle || (previous !== undefined && previous.shut)) {
      continue;
    }
    ctx.fillRect(originX + stepX(index, count, tileWidth), originY, 1, tileHeight);
  }
  ctx.globalAlpha = IDLE_ALPHA;
  ctx.fillStyle = ink.unknown;
  for (let index = 0; index < count; index += 1) {
    if (!points[index].idle) {
      continue;
    }
    ctx.fillRect(originX + stepX(index, count, tileWidth), originY, columnWidth, tileHeight);
  }
  ctx.globalAlpha = 1;

  ctx.strokeStyle = ink.borderStrong;
  ctx.strokeRect(originX + 0.5, originY + 0.5, tileWidth - 1, tileHeight - 1);

  ctx.fillStyle = ink.axisTick;
  ctx.font = LABEL_FONT;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'bottom';
  ctx.fillText(row.well, originX, originY - 2, tileWidth);
};

export const paintWall = (ctx: CanvasRenderingContext2D, paint: WallPaint): void => {
  const { layout, rows, series } = paint;
  ctx.clearRect(0, 0, layout.width, layout.height);
  const ink = wallInk(paint.palette);
  rows.forEach((row, index) => {
    const entry = series.get(row.well);
    if (entry === undefined) {
      return;
    }
    paintTile(ctx, entry, row, tileX(index, layout), tileY(index, layout), paint, ink);
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
