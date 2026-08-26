import { useEffect, useState, type RefObject } from 'react';

export interface BackdropShape {
  width: number;
  left: number;
  right: number;
}

const FALLBACK: BackdropShape = { width: 1000, left: 350, right: 650 };

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
      const bounds = container.getBoundingClientRect();
      const capsule = container.querySelector('.timeline-transport');
      if (bounds.width === 0 || capsule === null) {
        return;
      }
      const capsuleBounds = capsule.getBoundingClientRect();
      const centre = capsuleBounds.left + capsuleBounds.width / 2 - bounds.left;
      const settings = container.querySelector('.playback-settings-island');
      const panel = container.querySelector('.popover-panel');
      const date = container.querySelector('.time-scale-island');
      const baseHalf = Math.max(
        capsuleBounds.width / 2,
        settings === null ? 0 : settings.getBoundingClientRect().right - bounds.left - centre,
        date === null ? 0 : centre - (date.getBoundingClientRect().left - bounds.left)
      );
      const openHalf =
        panel === null ? baseHalf : panel.getBoundingClientRect().right - bounds.left - centre;
      const left = centre - baseHalf;
      const right = centre + Math.max(baseHalf, openHalf);
      if (!Number.isFinite(left) || !Number.isFinite(right)) {
        return;
      }
      setShape({ width: Math.round(bounds.width), left: Math.round(left), right: Math.round(right) });
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
