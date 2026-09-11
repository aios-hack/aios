import { useLayoutEffect, useState } from 'react';
import { useStageSettled } from '@/shared/lib/layout/useStageSettled';
import type { ReadoutBounds } from '@/pages/history-matrix/ChronoTooltip/ChronoTooltip';

export const OBSTRUCTION_SELECTORS = [
  '.time-scale-backdrop path',
  '.time-scale-backdrop',
  '.console-area-timeaxis'
];

export interface ViewportBox {
  width: number;
  height: number;
}

export const readoutBoundsOf = (
  stage: DOMRect,
  viewport: ViewportBox,
  clips: DOMRect[],
  obstruction: DOMRect | null
): ReadoutBounds => {
  let left = 0;
  let right = viewport.width;
  let top = 0;
  let bottom = viewport.height;
  for (const clip of clips) {
    left = Math.max(left, clip.left);
    right = Math.min(right, clip.right);
    top = Math.max(top, clip.top);
    bottom = Math.min(bottom, clip.bottom);
  }
  if (obstruction !== null && obstruction.top < bottom && obstruction.bottom > top) {
    bottom = Math.min(bottom, obstruction.top);
  }
  return {
    left: left - stage.left,
    right: right - stage.left,
    top: top - stage.top,
    bottom: Math.max(top - stage.top, bottom - stage.top)
  };
};

const obstructionRect = (stage: HTMLElement): DOMRect | null => {
  const doc = stage.ownerDocument;
  for (const selector of OBSTRUCTION_SELECTORS) {
    const node = doc.querySelector(selector);
    if (node === null) {
      continue;
    }
    const rect = node.getBoundingClientRect();
    if (rect.height > 0) {
      return rect;
    }
  }
  return null;
};

const clipRectsOf = (stage: HTMLElement): DOMRect[] => {
  const clips: DOMRect[] = [];
  let node = stage.parentElement;
  while (node !== null && node !== stage.ownerDocument.body) {
    const style = getComputedStyle(node);
    if (/auto|scroll|hidden|clip/.test(`${style.overflowX}${style.overflowY}`)) {
      clips.push(node.getBoundingClientRect());
    }
    node = node.parentElement;
  }
  return clips;
};

const sameBounds = (a: ReadoutBounds, b: ReadoutBounds): boolean =>
  a.left === b.left && a.right === b.right && a.top === b.top && a.bottom === b.bottom;

export const useReadoutBounds = (
  stage: HTMLDivElement | null,
  hovering: boolean
): ReadoutBounds => {
  const settled = useStageSettled();
  const [bounds, setBounds] = useState<ReadoutBounds>({
    left: 0,
    right: Number.POSITIVE_INFINITY,
    top: 0,
    bottom: Number.POSITIVE_INFINITY
  });

  useLayoutEffect(() => {
    if (stage === null || !settled) {
      return;
    }
    const measure = () => {
      const next = readoutBoundsOf(
        stage.getBoundingClientRect(),
        { width: window.innerWidth, height: window.innerHeight },
        clipRectsOf(stage),
        obstructionRect(stage)
      );
      setBounds((prev) => (sameBounds(prev, next) ? prev : next));
    };
    measure();
    const strip = stage.ownerDocument.querySelector('.time-scale');
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    strip?.addEventListener('transitionrun', measure);
    strip?.addEventListener('transitionend', measure);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
      strip?.removeEventListener('transitionrun', measure);
      strip?.removeEventListener('transitionend', measure);
    };
  }, [stage, hovering, settled]);

  return bounds;
};
