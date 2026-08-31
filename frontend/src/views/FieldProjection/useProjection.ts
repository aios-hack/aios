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

export const useProjectionTravel = (initial: number) => {
  const [t, setT] = useState(initial);
  const valueRef = useRef(initial);
  const frameRef = useRef<number | null>(null);

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
      const step = (now: number) => {
        const progress = Math.min((now - started) / TRAVEL_MS, 1);
        apply(from + (target - from) * easeInOut(progress));
        frameRef.current = progress < 1 ? requestAnimationFrame(step) : null;
      };
      frameRef.current = requestAnimationFrame(step);
    },
    [apply, stop]
  );

  return { t, travelTo, setImmediate };
};

export const usePlotGestures = () => {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const rectRef = useRef<DOMRect | null>(null);
  const [painted, setPainted] = useState<PaintedSize | null>(null);
  const initial = useMemo(() => createViewBox(FIELD_SIZE, FIELD_PAD), []);
  const { viewBox, zoomAtRatio, startPan, panBy, endPan, isPanning, hasDragged } =
    useViewBox(initial);

  useEffect(() => {
    const svg = svgRef.current;
    if (svg === null) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const factor = event.deltaY > 0 ? 1.12 : 1 / 1.12;
      const rect = svg.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) {
        zoomAtRatio(factor, 0.5, 0.5);
        return;
      }
      zoomAtRatio(
        factor,
        (event.clientX - rect.left) / rect.width,
        (event.clientY - rect.top) / rect.height
      );
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, [zoomAtRatio]);

  useEffect(() => {
    const svg = svgRef.current;
    if (svg === null) {
      return;
    }
    const measure = () => {
      const rect = svg.getBoundingClientRect();
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
      rectRef.current = svgRef.current?.getBoundingClientRect() ?? null;
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
