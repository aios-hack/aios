import { useCallback, useEffect, useRef, useState } from 'react';

interface WallBox {
  width: number;
  height: number;
}

export const useContainerBox = (): [
  (node: HTMLDivElement | null) => void,
  WallBox
] => {
  const [box, setBox] = useState<WallBox>({ width: 0, height: 0 });
  const observer = useRef<ResizeObserver | null>(null);

  useEffect(() => () => observer.current?.disconnect(), []);

  const attach = useCallback((node: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (node === null) {
      return;
    }
    const measure = (): WallBox => {
      const style = getComputedStyle(node);
      const inset = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      const strip = node.ownerDocument.querySelector('.console-area-timeaxis');
      const floor =
        strip === null ? window.innerHeight : strip.getBoundingClientRect().top;
      const top = node.getBoundingClientRect().top;
      return {
        width: Math.max(0, node.clientWidth - (Number.isFinite(inset) ? inset : 0)),
        height: Math.max(0, floor - top - parseFloat(style.paddingBottom))
      };
    };
    setBox(measure());
    if (typeof ResizeObserver !== 'function') {
      return;
    }
    const next = new ResizeObserver(() => {
      setBox(measure());
    });
    next.observe(node);
    const strip = node.ownerDocument.querySelector('.console-area-timeaxis');
    if (strip !== null) {
      next.observe(strip);
    }
    observer.current = next;
  }, []);

  return [attach, box];
};
