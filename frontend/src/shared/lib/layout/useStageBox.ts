import { useCallback, useEffect, useRef, useState } from 'react';

export interface StageBox {
  width: number;
  height: number;
}

export const useStageBox = (): [(node: HTMLDivElement | null) => void, StageBox] => {
  const [box, setBox] = useState<StageBox>({ width: 0, height: 0 });
  const observer = useRef<ResizeObserver | null>(null);

  useEffect(() => () => observer.current?.disconnect(), []);

  const attach = useCallback((node: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (node === null) {
      return;
    }
    const measure = (): StageBox => ({
      width: node.clientWidth,
      height: node.clientHeight
    });
    setBox(measure());
    if (typeof ResizeObserver !== 'function') {
      return;
    }
    const next = new ResizeObserver(() => {
      setBox(measure());
    });
    next.observe(node);
    observer.current = next;
  }, []);

  return [attach, box];
};
