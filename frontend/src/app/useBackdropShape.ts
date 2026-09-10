import { useEffect, useState, type RefObject } from 'react';
import { layoutBoxOf } from '../ui/shared/layoutBox';

export interface BackdropShape {
  width: number;
  left: number;
  right: number;
}

const FALLBACK: BackdropShape = { width: 1000, left: 350, right: 650 };

const boxOf = (
  container: HTMLElement,
  selector: string
): { left: number; right: number } | null => {
  const node = container.querySelector(selector);
  if (!(node instanceof HTMLElement)) {
    return null;
  }
  const box = layoutBoxOf(node, container);
  return { left: box.left, right: box.left + box.width };
};

export const useBackdropShape = (
  containerRef: RefObject<HTMLElement | null>,
  settingsOpen: boolean
): BackdropShape => {
  const [shape, setShape] = useState<BackdropShape>(FALLBACK);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const measure = () => {
      const width = container.offsetWidth;
      const capsule = boxOf(container, '.timeline-transport');
      if (width === 0 || capsule === null) {
        return;
      }
      const centre = (capsule.left + capsule.right) / 2;
      const settings = boxOf(container, '.playback-settings-island');
      const panel = boxOf(container, '.popover-panel');
      const date = boxOf(container, '.time-scale-island');
      const baseHalf = Math.max(
        (capsule.right - capsule.left) / 2,
        settings === null ? 0 : settings.right - centre,
        date === null ? 0 : centre - date.left
      );
      const openHalf = panel === null ? baseHalf : panel.right - centre;
      const left = centre - baseHalf;
      const right = centre + Math.max(baseHalf, openHalf);
      if (!Number.isFinite(left) || !Number.isFinite(right)) {
        return;
      }
      setShape({ width: Math.round(width), left: Math.round(left), right: Math.round(right) });
    };
    measure();
    const frame = window.requestAnimationFrame(measure);
    if (typeof ResizeObserver === 'undefined') {
      return () => window.cancelAnimationFrame(frame);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    const islands = container.querySelectorAll(
      '.timeline-transport, .playback-settings-island, .popover-panel'
    );
    for (const island of islands) {
      observer.observe(island);
    }
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [containerRef, settingsOpen]);

  return shape;
};
