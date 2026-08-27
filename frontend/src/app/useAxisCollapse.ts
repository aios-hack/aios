import { useCallback, useRef, type PointerEvent as ReactPointerEvent } from 'react';
import { usePlayback } from '../state/PlaybackContext';

const DRAG_THRESHOLD = 24;

interface AxisCollapse {
  collapsed: boolean;
  toggle: () => void;
  onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
}

export const useAxisCollapse = (): AxisCollapse => {
  const { axisCollapsed: collapsed, setAxisCollapsed: setCollapsed } = usePlayback();
  const collapsedRef = useRef(collapsed);
  collapsedRef.current = collapsed;

  const toggle = useCallback(() => {
    setCollapsed(!collapsedRef.current);
  }, [setCollapsed]);

  const onPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      event.preventDefault();
      const target = event.currentTarget;
      const originY = event.clientY;
      const pointerId = event.pointerId;
      let settled = false;

      target.setPointerCapture?.(pointerId);

      const finish = () => {
        target.removeEventListener('pointermove', onMove);
        target.removeEventListener('pointerup', onUp);
        target.removeEventListener('pointercancel', onUp);
        if (target.hasPointerCapture?.(pointerId)) {
          target.releasePointerCapture(pointerId);
        }
      };

      const onMove = (moveEvent: PointerEvent) => {
        if (settled) {
          return;
        }
        const delta = moveEvent.clientY - originY;
        if (Math.abs(delta) < DRAG_THRESHOLD) {
          return;
        }
        settled = true;
        setCollapsed(delta > 0);
        finish();
      };

      const onUp = () => {
        if (!settled) {
          settled = true;
          setCollapsed(!collapsedRef.current);
        }
        finish();
      };

      target.addEventListener('pointermove', onMove);
      target.addEventListener('pointerup', onUp);
      target.addEventListener('pointercancel', onUp);
    },
    [setCollapsed]
  );

  return { collapsed, toggle, onPointerDown };
};
