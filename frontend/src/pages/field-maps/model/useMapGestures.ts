import { useEffect, useMemo, useRef, useState } from 'react';
import { useViewBox, type ViewBox } from '@/shared/lib/viewbox/useViewBox';
import { coalescedZoom } from '@/entities/graph/model/useProjection';

export const MAP_PAD_RATIO = 0.04;

export const gridViewBox = (ni: number, nj: number): ViewBox => {
  const size = Math.max(ni, nj);
  const pad = size * MAP_PAD_RATIO;
  return {
    x: -pad + (ni - size) / 2,
    y: -pad + (nj - size) / 2,
    width: size + 2 * pad,
    height: size + 2 * pad
  };
};

export const gridPointAt = (
  box: ViewBox,
  ratioX: number,
  ratioY: number,
  nj: number
): { i: number; j: number } => ({
  i: Math.floor(box.x + ratioX * box.width),
  j: Math.floor(nj - (box.y + ratioY * box.height))
});

export const useMapGestures = (ni: number, nj: number) => {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const rectRef = useRef<DOMRect | null>(null);
  const [painted, setPainted] = useState<{ width: number; height: number } | null>(null);
  const initial = useMemo(() => gridViewBox(ni, nj), [ni, nj]);
  const { viewBox, zoomAtRatio, startPan, panBy, endPan, isPanning, hasDragged, reset } =
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
      const rect = svg.getBoundingClientRect();
      rectRef.current = rect;
      if (rect.width > 0 && rect.height > 0) {
        ratioX = (event.clientX - rect.left) / rect.width;
        ratioY = (event.clientY - rect.top) / rect.height;
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
      rectRef.current = rect;
      setPainted(
        rect.width > 0 && rect.height > 0 ? { width: rect.width, height: rect.height } : null
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
    onPointerUp: () => endPan(),
    onPointerLeave: () => endPan()
  };

  return {
    svgRef,
    rectRef,
    viewBox,
    painted,
    scale: initial.width / viewBox.width,
    handlers,
    hasDragged,
    reset
  };
};
