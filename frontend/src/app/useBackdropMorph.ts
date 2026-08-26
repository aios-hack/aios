import { useEffect, useRef } from 'react';
import { prefersReducedMotion } from '../views/FieldProjection/useProjection';

export const useBackdropMorph = (d: string, durationMs: number): ((node: SVGPathElement | null) => void) => {
  const nodeRef = useRef<SVGPathElement | null>(null);
  const previous = useRef(d);

  useEffect(() => {
    const node = nodeRef.current;
    if (node === null || previous.current === d) {
      return;
    }
    const from = previous.current;
    previous.current = d;
    if (prefersReducedMotion()) {
      node.setAttribute('d', d);
      return;
    }
    node.getAnimations().forEach((animation) => animation.cancel());
    node.animate([{ d: `path('${from}')` }, { d: `path('${d}')` }], {
      duration: durationMs,
      easing: 'cubic-bezier(0.22, 1, 0.36, 1)'
    });
  }, [d, durationMs]);

  return (node) => {
    nodeRef.current = node;
  };
};
