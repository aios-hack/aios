import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createViewBox, useViewBox } from '../shared/useViewBox';
import { easeInOut } from './interpolate';
import { FIELD_PAD, FIELD_SIZE } from './model';

export const TRAVEL_MS = 1350;

export const FALLBACK_PLOT_SIZE_PX = 700;

export interface PaintedSize {
  width: number;
  height: number;
}

export const unitsPerPixel = (
  viewBox: { width: number; height: number },
  painted: PaintedSize | null
): number => {
  if (painted === null || painted.width <= 0 || painted.height <= 0) {
    return viewBox.width / FALLBACK_PLOT_SIZE_PX;
  }
  return Math.max(viewBox.width / painted.width, viewBox.height / painted.height);
};

export const prefersReducedMotion = (): boolean => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
};

export const FRAME_BUDGET_MS = 16;

export const shouldCommitFrame = (
  now: number,
  lastCommit: number,
  lastCost: number
): boolean => now - lastCommit >= Math.max(FRAME_BUDGET_MS, lastCost);

export const useProjectionTravel = (initial: number) => {
  const [t, setT] = useState(initial);
  const valueRef = useRef(initial);
  const frameRef = useRef<number | null>(null);
  const costRef = useRef(0);

  const stop = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
  }, []);

  useEffect(() => stop, [stop]);

  const apply = useCallback((value: number) => {
    valueRef.current = value;
    setT(value);
  }, []);

  const setImmediate = useCallback(
    (value: number) => {
      stop();
      apply(value);
    },
    [apply, stop]
  );

  const travelTo = useCallback(
    (target: number) => {
      stop();
      const from = valueRef.current;
      if (
        prefersReducedMotion() ||
        typeof requestAnimationFrame !== 'function' ||
        Math.abs(target - from) < 1e-6
      ) {
        apply(target);
        return;
      }
      const started = performance.now();
      let lastCommit = started - FRAME_BUDGET_MS;
      let pending = false;
      const step = (now: number) => {
        if (pending) {
          costRef.current = now - lastCommit;
          pending = false;
        }
        const progress = Math.min((now - started) / TRAVEL_MS, 1);
        const done = progress >= 1;
        if (done || shouldCommitFrame(now, lastCommit, costRef.current)) {
          apply(from + (target - from) * easeInOut(progress));
          lastCommit = now;
          pending = !done;
        }
        frameRef.current = done ? null : requestAnimationFrame(step);
      };
      frameRef.current = requestAnimationFrame(step);
    },
    [apply, stop]
  );

  return { t, travelTo, setImmediate };
};

export const ZOOM_STEP = 1.12;

export const coalescedZoom = (deltas: readonly number[]): number => {
  let factor = 1;
  for (const delta of deltas) {
    factor *= delta > 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
  }
  return factor;
};

export const usePlotGestures = () => {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const rectRef = useRef<DOMRect | null>(null);
  const boxRef = useRef<DOMRect | null>(null);
  const [painted, setPainted] = useState<PaintedSize | null>(null);
  const initial = useMemo(() => createViewBox(FIELD_SIZE, FIELD_PAD), []);
  const { viewBox, zoomAtRatio, startPan, panBy, endPan, isPanning, hasDragged } =
    useViewBox(initial);

  useEffect(() => {
    const svg = svgRef.current;
    if (svg === null) {
      return;
    }
    let frame: number | null = null;
    const pending: number[] = [];
    let ratioX = 0.5;
    let ratioY = 0.5;
    const flush = () => {
      frame = null;
      const factor = coalescedZoom(pending);
      pending.length = 0;
      zoomAtRatio(factor, ratioX, ratioY);
    };
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = boxRef.current ?? svg.getBoundingClientRect();
      boxRef.current = rect;
      if (rect.width > 0 && rect.height > 0) {
        ratioX = (event.clientX - rect.left) / rect.width;
        ratioY = (event.clientY - rect.top) / rect.height;
      } else {
        ratioX = 0.5;
        ratioY = 0.5;
      }
      pending.push(event.deltaY);
      if (frame === null && typeof requestAnimationFrame === 'function') {
        frame = requestAnimationFrame(flush);
        return;
      }
      if (typeof requestAnimationFrame !== 'function') {
        flush();
      }
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      svg.removeEventListener('wheel', onWheel);
      if (frame !== null) {
        cancelAnimationFrame(frame);
      }
    };
  }, [zoomAtRatio]);

  useEffect(() => {
    const svg = svgRef.current;
    if (svg === null) {
      return;
    }
    const measure = () => {
      const rect = svg.getBoundingClientRect();
      boxRef.current = rect;
      setPainted(
        rect.width > 0 && rect.height > 0
          ? { width: rect.width, height: rect.height }
          : null
      );
    };
    measure();
    if (typeof ResizeObserver !== 'function') {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(svg);
    return () => observer.disconnect();
  }, []);

  const handlers = {
    onPointerDown: (event: { clientX: number; clientY: number }) => {
      const rect = svgRef.current?.getBoundingClientRect() ?? null;
      rectRef.current = rect;
      boxRef.current = rect;
      startPan(event.clientX, event.clientY);
    },
    onPointerMove: (event: { clientX: number; clientY: number }) => {
      if (!isPanning()) {
        return;
      }
      const rect = rectRef.current;
      panBy(event.clientX, event.clientY, rect?.width ?? 0, rect?.height ?? 0);
    },
    onPointerUp: () => {
      rectRef.current = null;
      endPan();
    },
    onPointerLeave: () => {
      rectRef.current = null;
      endPan();
    }
  };

  return {
    svgRef,
    viewBox,
    scale: initial.width / viewBox.width,
    unitsPerPixel: unitsPerPixel(viewBox, painted),
    handlers,
    hasDragged
  };
};
