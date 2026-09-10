import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { THREAD_HEIGHT, threadLength, threadPath } from './railThread';

const PITCH_VAR = '--size-jarvis-bead-pitch';

const pitchOf = (node: HTMLElement | null): number => {
  if (node === null || typeof getComputedStyle !== 'function') {
    return 0;
  }
  const raw = getComputedStyle(node).getPropertyValue(PITCH_VAR).trim();
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const HistoryThread = ({ count }: { count: number }) => {
  const ref = useRef<HTMLSpanElement>(null);
  const [pitch, setPitch] = useState(0);

  useEffect(() => {
    setPitch(pitchOf(ref.current));
  }, [count]);

  const width = Math.max(1, threadLength(count, pitch));
  const path = threadPath(count, pitch);

  return (
    <span className="jarvis-rail-thread" ref={ref} aria-hidden="true">
      {path.length === 0 ? null : (
        <svg
          width={width}
          height={THREAD_HEIGHT}
          viewBox={`0 0 ${width} ${THREAD_HEIGHT}`}
          preserveAspectRatio="none"
          focusable="false"
        >
          <path
            className="jarvis-rail-thread-path"
            d={path}
            fill="none"
            style={{ '--thread-length': `${width * 1.2}` } as CSSProperties}
          />
        </svg>
      )}
    </span>
  );
};
