import { useEffect, useRef, useState } from 'react';

const CLOSE_MS = 220;

export const useDeferredClose = (
  selectedWell: string | null
): { visibleWell: string | null; closing: boolean } => {
  const [visibleWell, setVisibleWell] = useState<string | null>(selectedWell);
  const [closing, setClosing] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (selectedWell !== null) {
      setVisibleWell(selectedWell);
      setClosing(false);
      return;
    }
    if (visibleWell === null) {
      return;
    }
    setClosing(true);
    timer.current = setTimeout(() => {
      setVisibleWell(null);
      setClosing(false);
      timer.current = null;
    }, CLOSE_MS);
    return () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
        timer.current = null;
      }
    };
  }, [selectedWell, visibleWell]);

  return { visibleWell, closing };
};
