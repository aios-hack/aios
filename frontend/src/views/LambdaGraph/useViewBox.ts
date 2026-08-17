import { useCallback, useRef, useState } from 'react';

export interface ViewBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

const MIN_SPAN = 8;
const MAX_SPAN = 600;

// Насколько далеко рамку можно увести за пределы содержимого: доля от её
// собственной ширины. Без ограничения панорама уводит граф за край и он
// теряется — вернуть его можно только перезагрузкой страницы.
const OVERSCROLL = 0.4;

export const createViewBox = (size: number, pad: number): ViewBox => ({
  x: -pad,
  y: -pad,
  width: size + 2 * pad,
  height: size + 2 * pad
});

const DRAG_SLOP = 3;

const clampToContent = (box: ViewBox, bounds: ViewBox): ViewBox => {
  const slackX = box.width * OVERSCROLL;
  const slackY = box.height * OVERSCROLL;
  const minX = bounds.x - slackX;
  const maxX = bounds.x + bounds.width - box.width + slackX;
  const minY = bounds.y - slackY;
  const maxY = bounds.y + bounds.height - box.height + slackY;
  return {
    ...box,
    x: minX > maxX ? (minX + maxX) / 2 : Math.min(Math.max(box.x, minX), maxX),
    y: minY > maxY ? (minY + maxY) / 2 : Math.min(Math.max(box.y, minY), maxY)
  };
};

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
      return clampToContent(
        {
          x: originX - ratioX * width,
          y: originY - ratioY * height,
          width,
          height
        },
        initial
      );
    });
  }, [initial]);

  /**
   * Зум по доле от размера окна, а не по координате viewBox.
   *
   * Нужен именно так, потому что колесо слушается нативно: обработчик живёт
   * в effect и видел бы viewBox того рендера, на котором был навешан. Доля
   * курсора от рамки от viewBox не зависит, а пересчёт в координаты идёт
   * внутри функционального обновления, где текущее состояние всегда свежее.
   */
  const zoomAtRatio = useCallback((factor: number, ratioX: number, ratioY: number) => {
    setViewBox((current) => {
      const width = Math.min(MAX_SPAN, Math.max(MIN_SPAN, current.width * factor));
      const height = Math.min(MAX_SPAN, Math.max(MIN_SPAN, current.height * factor));
      const originX = current.x + ratioX * current.width;
      const originY = current.y + ratioY * current.height;
      return clampToContent(
        {
          x: originX - ratioX * width,
          y: originY - ratioY * height,
          width,
          height
        },
        initial
      );
    });
  }, [initial]);

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
        return clampToContent(
          {
            ...current,
            x: current.x - (clientX - origin.x) * scaleX,
            y: current.y - (clientY - origin.y) * scaleY
          },
          initial
        );
      });
    },
    [initial]
  );

  const endPan = useCallback(() => {
    dragRef.current = null;
  }, []);

  const isPanning = useCallback(() => dragRef.current !== null, []);

  const hasDragged = useCallback(() => movedRef.current, []);

  return {
    viewBox,
    reset,
    zoomBy,
    zoomAtRatio,
    startPan,
    panBy,
    endPan,
    isPanning,
    hasDragged
  };
};
