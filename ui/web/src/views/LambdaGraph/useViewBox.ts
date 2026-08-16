import { useCallback, useRef, useState } from 'react';

export interface ViewBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

const MIN_SPAN = 8;
const MAX_SPAN = 600;

export const createViewBox = (size: number, pad: number): ViewBox => ({
  x: -pad,
  y: -pad,
  width: size + 2 * pad,
  height: size + 2 * pad
});

const DRAG_SLOP = 3;

export const useViewBox = (initial: ViewBox) => {
  const [viewBox, setViewBox] = useState<ViewBox>(initial);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const movedRef = useRef(false);

  const reset = useCallback(() => setViewBox(initial), [initial]);

  const zoomBy = useCallback((factor: number, originX: number, originY: number) => {
    setViewBox((current) => {
      const width = Math.min(MAX_SPAN, Math.max(MIN_SPAN, current.width * factor));
      const height = Math.min(MAX_SPAN, Math.max(MIN_SPAN, current.height * factor));
      const ratioX = (originX - current.x) / current.width;
      const ratioY = (originY - current.y) / current.height;
      return {
        x: originX - ratioX * width,
        y: originY - ratioY * height,
        width,
        height
      };
    });
  }, []);

  const startPan = useCallback((clientX: number, clientY: number) => {
    dragRef.current = { x: clientX, y: clientY };
    movedRef.current = false;
  }, []);

  const panBy = useCallback(
    (clientX: number, clientY: number, pixelWidth: number, pixelHeight: number) => {
      const origin = dragRef.current;
      if (origin === null) {
        return;
      }
      if (
        !movedRef.current &&
        Math.abs(clientX - origin.x) < DRAG_SLOP &&
        Math.abs(clientY - origin.y) < DRAG_SLOP
      ) {
        return;
      }
      movedRef.current = true;
      dragRef.current = { x: clientX, y: clientY };
      setViewBox((current) => {
        const scaleX = pixelWidth > 0 ? current.width / pixelWidth : 0;
        const scaleY = pixelHeight > 0 ? current.height / pixelHeight : 0;
        return {
          ...current,
          x: current.x - (clientX - origin.x) * scaleX,
          y: current.y - (clientY - origin.y) * scaleY
        };
      });
    },
    []
  );

  const endPan = useCallback(() => {
    dragRef.current = null;
  }, []);

  const isPanning = useCallback(() => dragRef.current !== null, []);

  const hasDragged = useCallback(() => movedRef.current, []);

  return { viewBox, reset, zoomBy, startPan, panBy, endPan, isPanning, hasDragged };
};
