import { useEffect, useRef, type RefObject } from 'react';
import { devicePixelRatioOf } from '@/shared/lib/canvas/canvasColors';
import type { WallLayout } from '@/pages/history-wall/model/layout';
import {
  paintWall,
  paintWallCursor,
  type WallPaint
} from '@/pages/history-wall/model/wallPainter';

const applyScale = (
  canvas: HTMLCanvasElement,
  layout: WallLayout,
  ratio: number
): CanvasRenderingContext2D | null => {
  const width = Math.round(layout.width * ratio);
  const height = Math.round(layout.height * ratio);
  const ctx = canvas.getContext('2d');
  if (ctx === null) {
    return null;
  }
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  } else {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
  }
  canvas.style.width = `${layout.width}px`;
  canvas.style.height = `${layout.height}px`;
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
